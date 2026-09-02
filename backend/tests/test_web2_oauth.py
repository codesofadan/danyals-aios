"""Web 2.0 OAuth connect - what it removes, what it must not claim to remove.

OAuth here replaces the TOKEN HUNT, never the signup. These platforms' own terms require
a human to create the account (Tumblr forbids registering accounts "automatically,
systematically, or programmatically"), so a flow that implied otherwise would be a terms
breach dressed as a feature.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.web2_oauth import (
    authorize_url,
    availability,
    credential_from_tokens,
    exchange_payload,
    spec_for,
)

pytestmark = pytest.mark.unit


class _Settings:
    """Only the fields the OAuth service reads."""

    def __init__(self, **kw: Any) -> None:
        self.web2_wordpress_client_id = kw.get("wp_id")
        self.web2_wordpress_client_secret = kw.get("wp_secret")
        self.web2_tumblr_client_id = kw.get("tumblr_id")
        self.web2_tumblr_client_secret = kw.get("tumblr_secret")
        self.google_oauth_client_id = kw.get("google_id")
        self.google_oauth_client_secret = kw.get("google_secret")
        self.web2_oauth_redirect_uri = kw.get("redirect", "https://api.example.com/cb")


# --------------------------------------------------------------------------- #
# Availability HOLDS rather than breaking.
# --------------------------------------------------------------------------- #
def test_an_unregistered_platform_holds_with_a_reason_a_human_can_act_on() -> None:
    ready, why = availability("WordPress.com", _Settings())
    assert not ready
    assert "register" in why.lower(), "the reason must name the fix, not just say no"


def test_a_registered_platform_is_available() -> None:
    assert availability("WordPress.com", _Settings(wp_id="abc"))[0]


def test_a_platform_with_no_oauth_path_says_so_rather_than_pretending() -> None:
    ready, why = availability("dev.to", _Settings())
    assert not ready
    assert "by hand" in why


def test_blogger_reuses_the_google_app_rather_than_asking_for_a_second_one() -> None:
    """Registering a second Google app for the same provider buys nothing, and asking
    for one is the kind of setup friction that leaves platforms unconnected."""
    assert spec_for("Blogger").client_id_setting == "google_oauth_client_id"  # type: ignore[union-attr]
    assert availability("Blogger", _Settings(google_id="g"))[0]


# --------------------------------------------------------------------------- #
# The consent URL.
# --------------------------------------------------------------------------- #
def test_the_consent_url_carries_the_state_and_the_registered_redirect() -> None:
    url = authorize_url(
        "WordPress.com", _Settings(wp_id="abc"), state="s-1", redirect_uri="https://api.example.com/cb"
    )
    assert url.startswith("https://public-api.wordpress.com/oauth2/authorize?")
    assert "state=s-1" in url
    assert "client_id=abc" in url
    assert "redirect_uri=https%3A%2F%2Fapi.example.com%2Fcb" in url


def test_blogger_asks_for_offline_access_or_the_account_dies_within_the_hour() -> None:
    """Without access_type=offline and prompt=consent Google returns an access-only
    token. The account would connect today and silently stop publishing tomorrow."""
    url = authorize_url("Blogger", _Settings(google_id="g"), state="s", redirect_uri="https://x/cb")
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_an_unregistered_platform_yields_no_url_at_all() -> None:
    assert authorize_url("Tumblr", _Settings(), state="s", redirect_uri="https://x/cb") == ""


# --------------------------------------------------------------------------- #
# The exchange.
# --------------------------------------------------------------------------- #
def test_the_exchange_body_carries_the_secret_and_the_same_redirect() -> None:
    url, form = exchange_payload(
        "Tumblr", _Settings(tumblr_id="i", tumblr_secret="s"), code="c", redirect_uri="https://x/cb"
    )
    assert url == "https://api.tumblr.com/v2/oauth2/token"
    assert form["client_id"] == "i"
    assert form["client_secret"] == "s"
    assert form["grant_type"] == "authorization_code"
    assert form["redirect_uri"] == "https://x/cb", "must match the authorize call exactly"


def test_a_refresh_token_is_preferred_over_a_short_lived_access_token() -> None:
    """Sealing the access token produces an account that works today and stops
    publishing within the hour - a failure that surfaces long after the connect."""
    cred = credential_from_tokens(
        "Blogger", {"access_token": "short", "refresh_token": "durable"}
    )
    assert cred == {"oauth_token": "durable"}


def test_an_access_only_response_is_still_used_where_that_is_all_a_platform_issues() -> None:
    assert credential_from_tokens("Tumblr", {"access_token": "only"}) == {"oauth_token": "only"}


def test_a_token_response_with_nothing_usable_yields_no_credential() -> None:
    """Better an empty credential the caller refuses than a row sealed with junk."""
    assert credential_from_tokens("Tumblr", {"error": "invalid_grant"}) == {}


# --------------------------------------------------------------------------- #
# The callback must stay reachable without auth.
# --------------------------------------------------------------------------- #
async def test_the_oauth_callback_is_reachable_unauthenticated() -> None:
    """The platform redirects a browser here with no credentials of ours. If this route
    ever required auth the flow would die at its last step, and the failure would look
    like the platform's fault. `state` is what makes it safe: single-use, short-lived,
    and mintable only by an authenticated lead."""
    import httpx

    from app.core.deps import get_redis
    from app.main import create_app

    class _Redis:
        async def get(self, _key: str) -> bytes | None:
            return None

        async def set(self, *_a: Any, **_kw: Any) -> None:
            return None

        async def delete(self, *_a: Any) -> None:
            return None

    app = create_app()
    app.dependency_overrides[get_redis] = lambda: _Redis()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.get(
                "/api/v1/offpage/web2/oauth/callback?error=access_denied",
                follow_redirects=False,
            )
            # A state we never minted must not be honoured, and must not 500 either.
            forged = await client.get(
                "/api/v1/offpage/web2/oauth/callback?code=c&state=forged",
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code != 401, "the platform's redirect carries no auth"
    assert denied.status_code in (302, 307), "it always ends in a redirect back to the UI"
    assert "web2Connect=error" in denied.headers["location"]
    # The unknown state is refused as expired rather than exchanged - the state token
    # IS the capability, so an attacker-supplied one must buy nothing.
    assert forged.status_code in (302, 307)
    assert "web2Connect=expired" in forged.headers["location"]
