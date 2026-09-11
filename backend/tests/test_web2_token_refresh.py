"""The OAuth bundle + refresh service (Phase 5) - what fixes the live Blogger 401.

The defect being guarded against, in both directions: seal only the ACCESS token and
the account dies within the hour; seal only the REFRESH token and it gets sent
verbatim as a Bearer header and 401s on the spot. The bundle keeps both, and
``fresh_access_token`` serves a CURRENT bearer - refreshing and re-sealing when the
margin runs out, passing a non-expiring PAT through untouched, and degrading
HONESTLY (None + account health + a lead notification naming the durable fix) when a
refresh fails. Every seam is injected: zero network, zero vault, zero DB here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import app.services.web2_token_refresh as wtr
from app.services.web2_oauth import parse_token_bundle
from app.services.web2_token_refresh import (
    OAUTH_BUNDLE_PLATFORMS,
    OAuthAccountRef,
    fresh_access_token,
    refreshing_lookup,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class _Settings:
    """Only the fields the OAuth service reads (mirrors test_web2_oauth)."""

    def __init__(self, **kw: Any) -> None:
        self.web2_wordpress_client_id = kw.get("wp_id")
        self.web2_wordpress_client_secret = kw.get("wp_secret")
        self.web2_tumblr_client_id = kw.get("tumblr_id")
        self.web2_tumblr_client_secret = kw.get("tumblr_secret")
        self.google_oauth_client_id = kw.get("google_id")
        self.google_oauth_client_secret = kw.get("google_secret")
        self.web2_oauth_redirect_uri = kw.get("redirect", "https://api.example.com/cb")


def _bundle(
    *, access: str = "acc-1", refresh: str = "ref-1", expires_at: str | None = None
) -> str:
    return json.dumps(
        {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": (_NOW + timedelta(hours=1)).isoformat() if expires_at is None else expires_at,
            "token_type": "Bearer",
        }
    )


def _cred(token_value: str, **extra: str) -> str:
    return json.dumps({"oauth_token": token_value, **extra})


class _Seams:
    """Recorder for the injected post/reseal/degrade/notify seams."""

    def __init__(self, response: dict[str, Any] | None = None, *, boom: bool = False) -> None:
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.reseals: list[dict[str, str]] = []
        self.degraded: list[str] = []
        self.notices: list[tuple[str, str, str]] = []
        self._response = response or {"access_token": "acc-new", "expires_in": 3600}
        self._boom = boom

    def post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        self.posts.append((url, form))
        if self._boom:
            raise RuntimeError("token refresh failed with status 400")
        return self._response

    def reseal(self, *, provider: str, label: str, secret: str) -> None:
        self.reseals.append({"provider": provider, "label": label, "secret": secret})


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> _Seams:
    s = _Seams()
    monkeypatch.setattr(wtr, "_degrade_account", lambda account_id: s.degraded.append(account_id))
    import app.services.notifications as notifications

    monkeypatch.setattr(
        notifications, "notify_leads_sync",
        lambda kind, title, body="": s.notices.append((kind, title, body)),
    )
    return s


def _token(raw_cred: str, seams: _Seams, *, platform: str = "Blogger", account_id: str = "acct-1") -> str | None:
    return fresh_access_token(
        OAuthAccountRef(platform=platform, vault_label="acct-1", account_id=account_id),
        settings=_Settings(google_id="g", google_secret="gs", tumblr_id="t", tumblr_secret="ts"),
        lookup=lambda *, provider, label: raw_cred,
        post=seams.post,
        reseal=seams.reseal,
        now=_NOW,
    )


# --------------------------------------------------------------------------- #
# Bundle detection is by shape.
# --------------------------------------------------------------------------- #
def test_a_bundle_parses_and_normalises() -> None:
    parsed = parse_token_bundle(_bundle(access="a", refresh="r"))
    assert parsed is not None
    assert parsed["access_token"] == "a" and parsed["refresh_token"] == "r"
    assert parsed["token_type"] == "Bearer"


def test_legacy_strings_and_junk_are_not_bundles() -> None:
    assert parse_token_bundle("1//legacy-google-refresh") is None
    assert parse_token_bundle("wpcom-pat-token") is None
    assert parse_token_bundle("{not json") is None
    assert parse_token_bundle(json.dumps(["a", "list"])) is None
    # A JSON object with NO token inside is junk, not a bundle - refusing it routes
    # the value through the legacy rules instead of serving an empty bearer.
    assert parse_token_bundle(json.dumps({"expires_at": "2026-01-01"})) is None


def test_exactly_the_three_oauth_platforms_route_through_the_service() -> None:
    assert {"WordPress.com", "Blogger", "Tumblr"} == OAUTH_BUNDLE_PLATFORMS


# --------------------------------------------------------------------------- #
# The margin: fresh is served, stale is refreshed.
# --------------------------------------------------------------------------- #
def test_a_fresh_access_token_is_served_with_no_network_and_no_reseal(seams: _Seams) -> None:
    token = _token(_cred(_bundle(expires_at=(_NOW + timedelta(hours=1)).isoformat())), seams)
    assert token == "acc-1"
    assert seams.posts == [] and seams.reseals == []


def test_a_token_inside_the_five_minute_margin_is_refreshed(seams: _Seams) -> None:
    """Two minutes of life left is not enough to publish with - the margin exists so
    a token cannot expire mid-publish."""
    token = _token(_cred(_bundle(expires_at=(_NOW + timedelta(minutes=2)).isoformat())), seams)
    assert token == "acc-new"
    assert len(seams.posts) == 1
    url, form = seams.posts[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "ref-1"


def test_a_bundle_with_no_expiry_never_goes_stale(seams: _Seams) -> None:
    """WordPress.com tokens do not expire; inventing a deadline would refresh (and
    risk breaking) a credential that works."""
    token = _token(_cred(_bundle(expires_at="")), seams, platform="WordPress.com")
    assert token == "acc-1"
    assert seams.posts == []


def test_a_refresh_reseals_the_updated_bundle_in_place(seams: _Seams) -> None:
    raw = _cred(_bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat()), blog_id="b-9")
    token = _token(raw, seams)
    assert token == "acc-new"
    (reseal,) = seams.reseals
    assert reseal["provider"] == "web2:Blogger" and reseal["label"] == "acct-1"
    creds = json.loads(reseal["secret"])
    assert creds["blog_id"] == "b-9", "the other credential fields must survive a reseal"
    bundle = json.loads(creds["oauth_token"])
    assert bundle["access_token"] == "acc-new"
    # Google returns no refresh_token on refresh: the durable half is KEPT.
    assert bundle["refresh_token"] == "ref-1"
    assert bundle["expires_at"], "the new absolute expiry is stamped"


def test_a_rotated_refresh_token_is_adopted(seams: _Seams) -> None:
    """Tumblr rotates the refresh token on use; keeping the old one would make the
    NEXT refresh fail."""
    seams._response = {"access_token": "acc-new", "refresh_token": "ref-2", "expires_in": 3600}
    _token(
        _cred(_bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat())), seams,
        platform="Tumblr",
    )
    bundle = json.loads(json.loads(seams.reseals[0]["secret"])["oauth_token"])
    assert bundle["refresh_token"] == "ref-2"


# --------------------------------------------------------------------------- #
# Legacy single-string credentials, detected by shape.
# --------------------------------------------------------------------------- #
def test_a_legacy_google_refresh_token_is_refreshed_and_upgraded(seams: _Seams) -> None:
    """The pre-bundle Blogger row: a bare `1//` refresh token that the old code sent
    as a Bearer (the 401 defect). First use trades it for an access token and
    upgrades the sealed row to a bundle."""
    token = _token(_cred("1//legacy-refresh", blog_id="b-1"), seams)
    assert token == "acc-new"
    (_url, form), = seams.posts
    assert form["refresh_token"] == "1//legacy-refresh"
    bundle = json.loads(json.loads(seams.reseals[0]["secret"])["oauth_token"])
    assert bundle["refresh_token"] == "1//legacy-refresh"
    assert bundle["access_token"] == "acc-new"


def test_a_legacy_non_expiring_pat_is_left_untouched(seams: _Seams) -> None:
    """A working WordPress.com bearer must not be 'repaired' into a bundle by guess -
    no refresh grant exists for it, and rewriting it can only break it."""
    token = _token(_cred("wpcom-pat"), seams, platform="WordPress.com")
    assert token == "wpcom-pat"
    assert seams.posts == [] and seams.reseals == []


# --------------------------------------------------------------------------- #
# Failure is honest: None + degraded + loud + notified.
# --------------------------------------------------------------------------- #
def test_a_failed_refresh_returns_none_degrades_and_notifies(seams: _Seams) -> None:
    seams._boom = True
    token = _token(_cred(_bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat())), seams)
    assert token is None, "a stale token must never be served as if it were fresh"
    assert seams.degraded == ["acct-1"]  # health='degraded' - the taxonomy's honest label
    assert len(seams.notices) == 1
    _kind, title, body = seams.notices[0]
    assert "Blogger" in title
    # The durable fix is a USER action and the notification must name it.
    assert "consent screen to Production" in body


def test_an_expired_bundle_with_no_refresh_token_fails_honestly(seams: _Seams) -> None:
    token = _token(
        _cred(_bundle(refresh="", expires_at=(_NOW - timedelta(minutes=1)).isoformat())), seams
    )
    assert token is None
    assert seams.posts == []  # nothing to post - there is no grant to run
    assert seams.degraded == ["acct-1"]


def test_a_missing_oauth_app_fails_honestly_rather_than_posting_nowhere(seams: _Seams) -> None:
    token = fresh_access_token(
        OAuthAccountRef(platform="Blogger", vault_label="acct-1", account_id="acct-1"),
        settings=_Settings(),  # no Google app registered
        lookup=lambda *, provider, label: _cred(
            _bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat())
        ),
        post=seams.post,
        reseal=seams.reseal,
        now=_NOW,
    )
    assert token is None and seams.posts == []
    assert seams.degraded == ["acct-1"]


def test_a_legacy_label_with_no_account_row_still_fails_loudly_without_a_health_write(
    seams: _Seams,
) -> None:
    """Pre-accounts rows have no web2_accounts row to degrade; the log + notification
    still fire, and nothing crashes trying to update a row that does not exist."""
    seams._boom = True
    token = _token(
        _cred(_bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat())), seams,
        account_id="",
    )
    assert token is None
    assert seams.degraded == []  # no account row -> no health write
    assert len(seams.notices) == 1  # but never silent


# --------------------------------------------------------------------------- #
# The publisher-facing lookup.
# --------------------------------------------------------------------------- #
def _lookup(raw: str | None, seams: _Seams, *, platform: str = "Blogger") -> Any:
    return refreshing_lookup(
        platform=platform, account_id="acct-1",
        settings=_Settings(google_id="g", google_secret="gs"),
        base=lambda *, provider, label: raw,
        post=seams.post, reseal=seams.reseal, now=_NOW,
    )


def test_the_lookup_hands_the_builder_a_plain_current_bearer(seams: _Seams) -> None:
    lookup = _lookup(_cred(_bundle(), blog_id="b-1"), seams)
    raw = lookup(provider="web2:Blogger", label="acct-1")
    creds = json.loads(raw)
    assert creds["oauth_token"] == "acc-1", "the builder must see a bearer, never a bundle"
    assert creds["blog_id"] == "b-1"


def test_the_lookup_returns_none_when_refresh_fails_so_the_publish_holds(seams: _Seams) -> None:
    seams._boom = True
    lookup = _lookup(_cred(_bundle(expires_at=(_NOW - timedelta(minutes=1)).isoformat())), seams)
    assert lookup(provider="web2:Blogger", label="acct-1") is None


def test_the_lookup_passes_a_missing_credential_straight_through(seams: _Seams) -> None:
    lookup = _lookup(None, seams)
    assert lookup(provider="web2:Blogger", label="acct-1") is None
    assert seams.posts == [] and seams.notices == []


def test_the_lookup_leaves_malformed_credentials_to_the_factorys_own_refusal(seams: _Seams) -> None:
    lookup = _lookup("{not json", seams)
    assert lookup(provider="web2:Blogger", label="acct-1") == "{not json"
    assert seams.posts == []


# --------------------------------------------------------------------------- #
# The defensive unwrap in the builder layer.
# --------------------------------------------------------------------------- #
def test_the_oauth_builders_never_send_a_bundle_as_a_bearer() -> None:
    from integrations.web2_credentials import _oauth_bearer, build_publisher

    assert _oauth_bearer(_bundle(access="acc-9")) == "acc-9"
    assert _oauth_bearer("plain-token") == "plain-token"
    assert _oauth_bearer("") == ""
    # A bundle with no access token yields '' so the client's own required-field
    # guard refuses it, rather than publishing with a JSON blob for a header.
    assert _oauth_bearer(json.dumps({"refresh_token": "only"})) == ""

    publisher = build_publisher(
        vault_label="acct-1", platform="Blogger",
        lookup=lambda *, provider, label: _cred(_bundle(access="acc-9"), blog_id="b-1"),
    )
    assert publisher is not None  # the bundle unwrapped into a working client
