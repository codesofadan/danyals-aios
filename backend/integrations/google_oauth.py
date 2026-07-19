"""Google OAuth2 authorization-code flow (7C): the shared front door for GSC + GA4.

ONE Google Cloud OAuth client covers both the Search Console (``webmasters.readonly``)
and GA4 (``analytics.readonly``) scopes in a single consent screen - simpler for
Danyal than registering two separate apps. Unlike GBP's Business Profile API, these
scopes are NOT approval-gated, so the flow is fully buildable and connectable the
moment ``google_oauth_client_id``/``google_oauth_client_secret``/
``google_oauth_redirect_uri`` land; a keyless deploy HOLDS (see
``app/modules/site_analytics/router.py`` / ``tasks.py``).

CREDENTIALS NEVER REST HERE: the authorization code is exchanged for a refresh token
that the CALLER (the oauth callback route) seals into the vault immediately - this
module only ever holds the code/token in memory for the duration of one request, and
never logs either (the client secret rides in the POST body, never a log line).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

logger = get_logger("integrations.google_oauth")

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# One shared consent screen requests BOTH scopes; a connected client's refresh
# token then reads whichever property (a GSC site / a GA4 property) it is later
# attached to - the scope grant does not itself pick a property.
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
)


def authorize_url(settings: Settings, *, state: str) -> str | None:
    """The Google consent-screen URL for ``state``, or ``None`` if the OAuth client
    is not configured (the HOLD path - see the module docstring)."""
    if not (settings.google_oauth_client_id and settings.google_oauth_redirect_uri):
        return None
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # request a refresh token, not just an access token
        "prompt": "consent",  # force a refresh token even on a re-connect
        "state": state,
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(settings: Settings, *, code: str) -> dict[str, Any]:
    """Exchange an authorization ``code`` for tokens. The ONE real network call in
    this module.

    Raises ``ProviderNotConfiguredError`` if the OAuth client is unset (guards
    direct misuse - the callback route itself is only reachable via a state token
    minted while the client WAS configured) and ``ProviderCallError`` on a
    non-2xx response, mirroring the shared HTTP seams' error taxonomy without
    inheriting ``HttpProviderClient`` (Google's token endpoint is one
    form-encoded POST, not a repeated JSON-body provider seam).
    """
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    redirect_uri = settings.google_oauth_redirect_uri
    if not (client_id and client_secret and redirect_uri):
        raise ProviderNotConfiguredError(
            "Google OAuth exchange unavailable: set GOOGLE_OAUTH_CLIENT_ID / "
            "GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI"
        )
    try:
        import httpx
    except ImportError as exc:  # httpx is a base dependency; guard mirrors http_client.py
        raise ProviderNotConfiguredError("google_oauth unavailable: install httpx") from exc

    body = {
        "client_id": client_id,
        "client_secret": client_secret.get_secret_value(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    try:
        response = httpx.post(_TOKEN_URL, data=body, timeout=20.0)
    except httpx.TransportError as exc:
        raise ProviderCallError(f"google_oauth token exchange failed: {exc}") from exc
    if response.status_code >= 400:
        # Never log the body - it can echo the auth code / client secret.
        logger.error("google_oauth_exchange_failed", status=response.status_code)
        raise ProviderCallError(
            f"google_oauth token exchange failed with status {response.status_code}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or "access_token" not in payload:
        raise ProviderCallError("google_oauth token exchange returned an unexpected body")
    return payload


def refresh_access_token(settings: Settings, *, refresh_token: str) -> str:
    """Exchange a sealed refresh token for a short-lived access token. Called by a
    sync task right before a GSC/GA4 read - access tokens are never stored, only
    the refresh token (in the vault). Raises the same two errors as
    :func:`exchange_code`."""
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    if not (client_id and client_secret):
        raise ProviderNotConfiguredError(
            "Google OAuth refresh unavailable: set GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET"
        )
    try:
        import httpx
    except ImportError as exc:
        raise ProviderNotConfiguredError("google_oauth unavailable: install httpx") from exc

    body = {
        "client_id": client_id,
        "client_secret": client_secret.get_secret_value(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        response = httpx.post(_TOKEN_URL, data=body, timeout=20.0)
    except httpx.TransportError as exc:
        raise ProviderCallError(f"google_oauth token refresh failed: {exc}") from exc
    if response.status_code >= 400:
        logger.error("google_oauth_refresh_failed", status=response.status_code)
        raise ProviderCallError(
            f"google_oauth token refresh failed with status {response.status_code}"
        )
    payload = response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise ProviderCallError("google_oauth token refresh returned no access_token")
    return str(token)
