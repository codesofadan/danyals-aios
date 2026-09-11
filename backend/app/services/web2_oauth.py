"""OAuth connect for the Web 2.0 platforms that offer it.

WHAT THIS REMOVES. On WordPress.com, Blogger and Tumblr the operator otherwise creates
the account, then goes hunting for a token in a developer console and pastes it back.
OAuth replaces that last half with a consent screen: the operator clicks Connect, signs
in as the client, and the token arrives sealed without ever being seen or pasted.

WHAT IT DOES NOT CHANGE. The ACCOUNT is still created by a human, because these
platforms' own terms require it - Tumblr forbids registering accounts "automatically,
systematically, or programmatically". OAuth authorises an account that already exists;
it is not a signup bypass, and treating it as one would be the terms breach the guided
lane exists to avoid. Tumblr also still requires per-post approval at publish time.

HOLDS RATHER THAN FAILS. Each platform needs an OAuth app the agency registers once. Any
platform without one reports ``held`` with the reason, exactly as the Google connect
flow does, so an unconfigured platform is a visible "not set up yet" instead of a broken
button.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class OAuthSpec:
    """One platform's OAuth endpoints and the credential shape a token becomes."""

    platform: str
    authorize_endpoint: str
    token_endpoint: str
    scope: str = ""
    #: Which settings hold this platform's registered app.
    client_id_setting: str = ""
    client_secret_setting: str = ""
    #: The credential field the access token is stored as, matching
    #: PLATFORM_CREDENTIAL_FIELDS so the publisher can read it back unchanged.
    token_field: str = "oauth_token"
    #: Fields the operator must still supply (a blog id cannot come from consent).
    manual_fields: tuple[str, ...] = ()


SPECS: dict[str, OAuthSpec] = {
    "WordPress.com": OAuthSpec(
        platform="WordPress.com",
        authorize_endpoint="https://public-api.wordpress.com/oauth2/authorize",
        token_endpoint="https://public-api.wordpress.com/oauth2/token",
        scope="global",
        client_id_setting="web2_wordpress_client_id",
        client_secret_setting="web2_wordpress_client_secret",
        token_field="oauth_token",
        manual_fields=("site",),
    ),
    "Tumblr": OAuthSpec(
        platform="Tumblr",
        authorize_endpoint="https://www.tumblr.com/oauth2/authorize",
        token_endpoint="https://api.tumblr.com/v2/oauth2/token",
        scope="basic write offline_access",
        client_id_setting="web2_tumblr_client_id",
        client_secret_setting="web2_tumblr_client_secret",
        token_field="oauth_token",
        manual_fields=("blog",),
    ),
    "Blogger": OAuthSpec(
        platform="Blogger",
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        scope="https://www.googleapis.com/auth/blogger",
        # Reuses the Google app the analytics module already registers, rather than
        # asking the agency to register a second one for the same provider.
        client_id_setting="google_oauth_client_id",
        client_secret_setting="google_oauth_client_secret",
        token_field="oauth_token",
        manual_fields=("blog_id",),
    ),
}


def spec_for(platform: str) -> OAuthSpec | None:
    """The OAuth spec for a platform, or None when it has no OAuth path at all."""
    return SPECS.get(platform)


def _setting(settings: Any, name: str) -> str:
    value = getattr(settings, name, None)
    if value is None:
        return ""
    secret = getattr(value, "get_secret_value", None)
    return str(secret() if callable(secret) else value)


def availability(platform: str, settings: Any) -> tuple[bool, str]:
    """Whether Connect can run for this platform, and why not when it cannot."""
    spec = spec_for(platform)
    if spec is None:
        return (False, f"{platform} has no OAuth connect - add its token by hand.")
    if not _setting(settings, spec.client_id_setting):
        return (
            False,
            f"No {platform} app is registered yet, so Connect cannot run. Register one "
            "once for the agency, then every client connects with a click.",
        )
    return (True, "")


def authorize_url(platform: str, settings: Any, *, state: str, redirect_uri: str) -> str:
    """The consent URL to send the operator to. Empty when the platform is unavailable."""
    spec = spec_for(platform)
    if spec is None:
        return ""
    client_id = _setting(settings, spec.client_id_setting)
    if not client_id:
        return ""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if spec.scope:
        params["scope"] = spec.scope
    if spec.platform == "Blogger":
        # Without these Google returns an access-only token that dies in an hour, and
        # the account silently stops publishing later rather than failing at connect.
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    return f"{spec.authorize_endpoint}?{urlencode(params)}"


def exchange_payload(
    platform: str, settings: Any, *, code: str, redirect_uri: str
) -> tuple[str, dict[str, str]]:
    """The token-endpoint URL and form body for the code exchange."""
    spec = spec_for(platform)
    if spec is None:
        return ("", {})
    return (
        spec.token_endpoint,
        {
            "client_id": _setting(settings, spec.client_id_setting),
            "client_secret": _setting(settings, spec.client_secret_setting),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_payload(
    platform: str, settings: Any, *, refresh_token: str
) -> tuple[str, dict[str, str]]:
    """The token-endpoint URL and form body for the REFRESH grant.

    This is the half the original connect flow was missing, and its absence was a
    live defect: Blogger's refresh token was sealed and then sent VERBATIM as a
    Bearer header, which Google answers with 401 - the account connected once and
    never published. The refresh service (``web2_token_refresh``) posts this form to
    trade the durable refresh token for a short-lived access token whenever the
    sealed one is stale. Empty URL when the platform has no OAuth path or no
    registered app - the caller degrades, it does not guess."""
    spec = spec_for(platform)
    if spec is None:
        return ("", {})
    client_id = _setting(settings, spec.client_id_setting)
    if not client_id:
        return ("", {})
    return (
        spec.token_endpoint,
        {
            "client_id": client_id,
            "client_secret": _setting(settings, spec.client_secret_setting),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


def token_expires_at(tokens: dict[str, Any]) -> str:
    """Server-side absolute expiry from the response's relative ``expires_in``.

    Stamped HERE, at exchange time, because ``expires_in`` is meaningless later -
    "3600 seconds" sealed in a vault answers nothing next week. Empty when the
    platform does not expire its tokens (WordPress.com), which the refresh service
    reads as "never stale"."""
    try:
        seconds = int(tokens.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return ""
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def credential_from_tokens(platform: str, tokens: dict[str, Any]) -> dict[str, str]:
    """Turn a token response into the credential the publisher reads.

    Seals the FULL BUNDLE - {access_token, refresh_token, expires_at, token_type} as
    a JSON string in the platform's token field - rather than choosing one token.
    Choosing was the original sin, and both choices lose: seal the access token and
    the account quietly stops publishing within the hour; seal the refresh token and
    it gets sent as a Bearer header and 401s on the spot (the live Blogger defect).
    The bundle keeps both halves so ``web2_token_refresh.fresh_access_token`` can
    serve a current access token forever, re-sealing as it refreshes. The vault path
    is unchanged: same provider/label row, same credential dict shape - only the
    field's VALUE is now a bundle instead of a bare token.
    """
    spec = spec_for(platform)
    if spec is None:
        return {}
    access = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token") or "")
    if not access and not refresh:
        return {}
    bundle = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": token_expires_at(tokens),
        "token_type": str(tokens.get("token_type") or "Bearer"),
    }
    return {spec.token_field: json.dumps(bundle)}


def parse_token_bundle(value: str) -> dict[str, str] | None:
    """The bundle inside an OAuth credential field, or ``None`` for a LEGACY value.

    Detection is BY SHAPE, not by a version marker: a bundle is a JSON object
    carrying at least one token key; anything else - including the bare tokens every
    pre-bundle row holds - is legacy and returns ``None`` so the caller applies the
    legacy rules (a Google-style refresh token is refreshed; a non-expiring PAT is
    passed through untouched)."""
    text = (value or "").strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not (parsed.get("access_token") or parsed.get("refresh_token")):
        return None
    return {
        "access_token": str(parsed.get("access_token") or ""),
        "refresh_token": str(parsed.get("refresh_token") or ""),
        "expires_at": str(parsed.get("expires_at") or ""),
        "token_type": str(parsed.get("token_type") or "Bearer"),
    }
