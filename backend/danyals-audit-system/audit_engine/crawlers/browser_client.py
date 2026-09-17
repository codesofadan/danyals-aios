"""Browser-impersonating async HTTP client.

Wraps `curl_cffi.requests.AsyncSession` to bypass Cloudflare's TLS fingerprint
detection. curl_cffi uses BoringSSL (Chromium's actual TLS stack), so the
JA3/JA4 fingerprint our requests produce is indistinguishable from a real
Chrome browser.

This client exposes the subset of `httpx.AsyncClient` interface that the
crawler + robots/sitemap parsers depend on:
  - `async with` context manager
  - `.get(url) -> Response` with `.status_code`, `.text`, `.content`,
    `.headers`, `.url`, `.history`, `.http_version`
  - `CrawlerTransportError` exception (caught in place of httpx.TransportError)

Why this exists
---------------
Cloudflare bot detection is multi-layer:
  1. User-Agent string  - trivial to spoof
  2. TLS handshake fingerprint (JA3/JA4) - reveals Python httpx
  3. HTTP/2 SETTINGS frame order - also unique to httpx
  4. JavaScript challenge - requires real browser execution
  5. IP reputation - blocks known data-center ranges

curl_cffi handles layers 1-3 by using Chromium's actual TLS + HTTP/2 stack.
For layer 4 (JS challenge), a headless browser (Playwright) is still required;
this client returns the challenge HTML in that case and the audit downgrades
gracefully. For layer 5, a residential proxy is needed - out of scope here.

Coverage in practice: ~80% of Cloudflare-protected sites become crawlable.
"""

from __future__ import annotations

from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

# Default Chrome impersonation profile. Bumping this string when curl_cffi
# adds newer Chrome JA3 profiles keeps the fingerprint fresh against
# Cloudflare's rolling detection rules.
DEFAULT_IMPERSONATE = "chrome120"


class CrawlerTransportError(Exception):
    """Raised when the underlying HTTP transport fails (DNS, TLS, timeout)."""


class _Response:
    """httpx.Response-compatible facade over a curl_cffi Response."""

    __slots__ = ("_r",)

    def __init__(self, raw: Any) -> None:
        self._r = raw

    @property
    def status_code(self) -> int:
        return int(self._r.status_code)

    @property
    def text(self) -> str:
        return self._r.text or ""

    @property
    def content(self) -> bytes:
        return self._r.content or b""

    @property
    def headers(self) -> Any:
        return self._r.headers

    @property
    def url(self) -> str:
        return str(self._r.url)

    @property
    def history(self) -> list[Any]:
        # curl_cffi exposes redirect history as a list of prior responses (or
        # absent on no-redirect). Wrap each in our facade so attribute access
        # is uniform.
        raw_hist = getattr(self._r, "history", None) or []
        return [_Response(h) for h in raw_hist]

    @property
    def http_version(self) -> str | None:
        # curl_cffi exposes the negotiated HTTP version via the http_version
        # integer (10, 11, 20, 30). Map to the httpx-style string.
        v = getattr(self._r, "http_version", None)
        return {10: "HTTP/1.0", 11: "HTTP/1.1", 20: "HTTP/2", 30: "HTTP/3"}.get(v)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise CrawlerTransportError(f"HTTP {self.status_code}")


class BrowserClient:
    """Cloudflare-resistant async HTTP client.

    Drop-in subset of `httpx.AsyncClient` for the crawl + parser code paths.
    Use as an async context manager:

        async with BrowserClient(timeout=15.0) as client:
            resp = await client.get("https://example.com/")
            print(resp.status_code, resp.text)
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        follow_redirects: bool = True,
        max_redirects: int = 5,
        impersonate: str = DEFAULT_IMPERSONATE,
        # The user_agent + http2 kwargs are accepted for httpx-compat but
        # ignored: curl_cffi sets both based on the impersonation profile.
        user_agent: str | None = None,
        http2: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._follow_redirects = follow_redirects
        self._max_redirects = max_redirects
        self._impersonate = impersonate
        self._extra_headers = dict(headers or {})
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> BrowserClient:
        self._session = AsyncSession(
            timeout=self._timeout,
            impersonate=self._impersonate,
            headers=self._extra_headers or None,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> _Response:
        if self._session is None:
            raise RuntimeError("BrowserClient used outside `async with` context")
        try:
            r = await self._session.get(
                url,
                headers=headers,
                params=params,
                allow_redirects=self._follow_redirects,
                max_redirects=self._max_redirects,
            )
        except RequestException as e:
            raise CrawlerTransportError(f"{type(e).__name__}: {e}") from e
        except Exception as e:  # noqa: BLE001
            # curl_cffi can raise low-level cffi errors that don't inherit
            # from RequestException; treat them as transport failures too.
            raise CrawlerTransportError(f"{type(e).__name__}: {e}") from e
        return _Response(r)
