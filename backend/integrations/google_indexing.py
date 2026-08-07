"""Google Indexing API seam - the ONLY door to ``urlNotifications:publish``.

The Google Indexing API (https://developers.google.com/search/apis/indexing-api) lets
you tell Google a URL was updated or deleted:
``POST https://indexing.googleapis.com/v3/urlNotifications:publish``
with ``{"url": ..., "type": "URL_UPDATED"}``. It is FREE (quota-limited), authed with a
Google **service account** bearing the ``https://www.googleapis.com/auth/indexing``
scope. We REUSE the SAME service-account credential the SheetStore already uses
(``GOOGLE_SHEETS_SA_JSON``) - no new key.

SETUP CAVEAT (documented, not enforceable here): the service account's ``client_email``
must be added as an OWNER of the target property in Google Search Console, AND the
Indexing API must be enabled in that Google Cloud project. Until both are done Google
returns 403; the seam records that as an ``error`` row and moves on - never a crash.

Auth is the standard service-account JWT-bearer flow, done SELF-CONTAINED over the
shared async ``httpx.AsyncClient`` (no google client libs needed): sign a short JWT with
the SA private key (RS256, via pyjwt - already a dep) asserting the ``indexing`` scope,
exchange it at ``https://oauth2.googleapis.com/token`` for a bearer access token (cached
until shortly before expiry), then POST the notification. Two impls satisfy the async
``GoogleIndexing`` Protocol:

* ``GoogleIndexingClient`` - real, GATED on ``GOOGLE_INDEXING_ENABLED`` + a valid
  ``GOOGLE_SHEETS_SA_JSON``. NON-RAISING: any auth / transport / HTTP failure returns
  ``GoogleIndexingResult(ok=False, ...)`` - never an exception. The private key never
  leaves the object + is never logged.
* ``FakeGoogleIndexing`` - deterministic, offline: records every publish + returns a
  fixed result, so the service + endpoint tests run keyless.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from app.logging_setup import get_logger

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.google_indexing")

_PUBLISH_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/indexing"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_TIMEOUT = 15.0
_TOKEN_TTL = 3600  # Google caps SA tokens at 1h
_TOKEN_SKEW = 60   # refresh a minute early so an in-flight call never uses a dead token


@dataclass(frozen=True)
class GoogleIndexingResult:
    """The verdict of one publish: ``ok`` + a short sanitized ``detail`` line."""

    ok: bool
    detail: str = ""


@runtime_checkable
class GoogleIndexing(Protocol):
    async def publish(
        self, http: httpx.AsyncClient, *, url: str, type_: str = "URL_UPDATED"
    ) -> GoogleIndexingResult: ...


class GoogleIndexingClient:
    """Real async ``GoogleIndexing`` over the shared ``httpx.AsyncClient``.

    The SA credential JSON is parsed once at construction; the private key + client
    email are held in-object and NEVER logged. An access token is minted lazily on the
    first publish and cached in-object until shortly before it expires.
    """

    provider = "google_indexing"

    def __init__(self, *, credentials_json: str) -> None:
        info = json.loads(credentials_json)
        if not isinstance(info, dict):
            raise ValueError("service-account credential must be a JSON object")
        self._client_email = str(info["client_email"])
        self._private_key = str(info["private_key"])
        self._token_uri = str(info.get("token_uri") or _TOKEN_ENDPOINT)
        self._token: str = ""
        self._token_exp: float = 0.0

    def _sign_assertion(self, now: int) -> str:
        import jwt  # pyjwt[crypto] - already a base dep

        claims = {
            "iss": self._client_email,
            "scope": _SCOPE,
            "aud": self._token_uri,
            "iat": now,
            "exp": now + _TOKEN_TTL,
        }
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    async def _access_token(self, http: httpx.AsyncClient) -> str | None:
        """Return a cached-or-freshly-minted bearer token, or ``None`` on any failure."""
        now = time.time()
        if self._token and now < self._token_exp - _TOKEN_SKEW:
            return self._token
        try:
            assertion = self._sign_assertion(int(now))
            resp = await http.post(
                self._token_uri,
                data={"grant_type": _JWT_GRANT, "assertion": assertion},
                timeout=_TIMEOUT,
            )
        except Exception:
            logger.info("google_indexing_token_degraded", reason="transport_error")
            return None
        if resp.status_code != 200:
            logger.info("google_indexing_token_rejected", status=resp.status_code)
            return None
        try:
            token = str(resp.json().get("access_token") or "")
        except ValueError:
            return None
        if not token:
            return None
        self._token = token
        self._token_exp = now + _TOKEN_TTL
        return token

    async def publish(
        self, http: httpx.AsyncClient, *, url: str, type_: str = "URL_UPDATED"
    ) -> GoogleIndexingResult:
        token = await self._access_token(http)
        if token is None:
            return GoogleIndexingResult(ok=False, detail="auth failed")
        try:
            resp = await http.post(
                _PUBLISH_ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
                json={"url": url, "type": type_},
                timeout=_TIMEOUT,
            )
        except Exception:
            logger.info("google_indexing_degraded", reason="transport_error")
            return GoogleIndexingResult(ok=False, detail="transport error")
        if resp.status_code == 200:
            return GoogleIndexingResult(ok=True, detail="200 published")
        # 403 = SA not a Search Console owner / API not enabled; 429 = quota. Log the
        # STATUS only (never the body - it may echo the URL/reason with account detail).
        logger.info("google_indexing_rejected", status=resp.status_code)
        return GoogleIndexingResult(ok=False, detail=f"http {resp.status_code}")


@dataclass
class PublishedUrl:
    """One captured publish (FakeGoogleIndexing), for test assertions."""

    url: str
    type_: str


@dataclass
class FakeGoogleIndexing:
    """Deterministic, offline ``GoogleIndexing`` for the service + endpoint unit tests.

    Records every publish into ``published`` and returns ``result`` (default ok), so a
    test can prove the engine fired + with what, with zero network / no SA key."""

    result: GoogleIndexingResult = field(
        default_factory=lambda: GoogleIndexingResult(ok=True, detail="200 published")
    )
    published: list[PublishedUrl] = field(default_factory=list)

    async def publish(
        self, http: httpx.AsyncClient, *, url: str, type_: str = "URL_UPDATED"
    ) -> GoogleIndexingResult:
        self.published.append(PublishedUrl(url=url, type_=type_))
        return self.result


def google_indexing_from_settings(settings: Settings) -> GoogleIndexing | None:
    """A real ``GoogleIndexingClient`` when ``GOOGLE_INDEXING_ENABLED`` is on AND a valid
    ``GOOGLE_SHEETS_SA_JSON`` is present, else ``None``.

    Degrades to ``None`` (never raises) when disabled or the credential is absent /
    malformed - the indexing service then records the ``google`` engine as ``skipped``
    (not configured), never a crash. No secret is ever logged.
    """
    if not settings.google_indexing_enabled:
        logger.info("google_indexing_degraded", reason="disabled")
        return None
    creds = settings.google_sheets_sa_json
    if not creds:
        logger.info("google_indexing_degraded", reason="missing_credentials")
        return None
    try:
        return GoogleIndexingClient(credentials_json=creds.get_secret_value())
    except Exception as exc:  # malformed JSON / missing fields - never echo the JSON
        logger.info("google_indexing_degraded", reason=type(exc).__name__)
        return None
