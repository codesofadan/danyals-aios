"""Firecrawl RENDER + SCREENSHOT seam (site-design analysis).

THE BUG THIS SEAM FIXES: ``POST /content/site-design`` used to fetch the target site
with a plain httpx GET - no JS execution, no CSS. A modern site returns a near-empty
JS shell with no styles, so Claude saw no real design evidence and every extracted
profile collapsed to the dataclass defaults (the SAME templated palette/fonts/sections
for EVERY site). Firecrawl RENDERS the page (runs its JS, applies its CSS) and returns
clean markdown PLUS a full-page SCREENSHOT of what the site actually looks like, which
Claude then analyzes with VISION - so the profile genuinely varies per site.

This is the ONLY door to Firecrawl. The site-design endpoint reaches it exclusively
through the async ``Firecrawl`` Protocol, so the analysis unit-tests on a
``FakeFirecrawl`` with zero network. Two impls satisfy the Protocol, mirroring every
other provider seam (``resend`` / ``wordpress``):

* ``FirecrawlClient`` - real, over the SHARED async ``httpx.AsyncClient`` the app opens
  in its lifespan (async, unlike the sync content seams). KEY-GATED on
  ``FIRECRAWL_API_KEY``; the key rides in a Bearer ``Authorization`` header and is NEVER
  logged. Absent key -> ``ProviderNotConfiguredError`` naming the fix.
* ``FakeFirecrawl`` - deterministic, offline: returns a fixed ``FirecrawlPage`` (or
  ``None`` to exercise the degrade path), so the endpoint + analysis tests run keyless.

``firecrawl_from_settings`` returns a real client when the key is present and degrades
to ``None`` otherwise - the endpoint then FALLS BACK to the plain-httpx fetcher (no
screenshot), never a crash.

THE SCREENSHOT RESPONSE SHAPE (handled defensively): Firecrawl's ``screenshot`` format
returns either a hosted PNG URL (the common case) OR an inline ``data:image/png;base64,``
URI OR raw base64, depending on plan/version. ``firecrawl_scrape`` normalises all three
to a bounded base64 PNG string (fetching + encoding a URL, stripping a data-URI prefix,
or passing raw base64 through) so the vision caller always gets ``image/png`` base64.
The whole call is NON-RAISING: any transport / HTTP / parse failure degrades to ``None``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.firecrawl")

_INSTALL_HINT = "set FIRECRAWL_API_KEY to render the site (JS + CSS) and capture a screenshot"
_DEFAULT_BASE_URL = "https://api.firecrawl.dev"
_SCRAPE_PATH = "/v1/scrape"

# Bounds. The POST that renders the page can take a while (a heavy SPA), so it gets a
# generous timeout; the screenshot fetch is a plain asset GET. The screenshot is capped
# so a hostile / huge capture cannot balloon the vision prompt (Anthropic vision accepts
# ~5MB/image; we stay well under). A capture past the cap is DROPPED (screenshot=None),
# never truncated - a half a PNG is not a valid image.
_SCRAPE_TIMEOUT = 60.0
_SCREENSHOT_TIMEOUT = 20.0
_MAX_SCREENSHOT_BYTES = 4_000_000  # decoded PNG bytes


@dataclass(frozen=True)
class FirecrawlPage:
    """One rendered page: the cleaned ``markdown`` and an optional base64 PNG
    ``screenshot_b64`` (already normalised to raw base64, no ``data:`` prefix)."""

    markdown: str
    screenshot_b64: str | None = None


@runtime_checkable
class Firecrawl(Protocol):
    """Render one URL and return its markdown + (optionally) a screenshot, or ``None``.

    ``http`` is the caller's SHARED async client (the app-lifespan pool); passing it in
    keeps this seam poolless + injectable. ``want_screenshot`` gates the (paid, slower)
    screenshot format. NON-RAISING: any failure returns ``None`` so the caller degrades.
    """

    async def scrape(
        self, http: httpx.AsyncClient, url: str, *, want_screenshot: bool
    ) -> FirecrawlPage | None: ...


async def firecrawl_scrape(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    url: str,
    want_screenshot: bool,
) -> FirecrawlPage | None:
    """Render ``url`` via Firecrawl and return a :class:`FirecrawlPage`, or ``None``.

    POSTs ``{base_url}/v1/scrape`` with ``formats: ["markdown"(, "screenshot@fullPage")]``
    and ``onlyMainContent: false`` (we want the WHOLE chrome - header/nav/hero/footer - to
    read the layout, not just the article body), under Bearer auth. The screenshot is the
    ``@fullPage`` variant (the ENTIRE page top-to-bottom, not just the viewport), so the
    vision analysis SEES every section down to the footer - the plain ``screenshot`` format
    would clip everything below the fold. Degrades to ``None`` on ANY failure (transport /
    non-200 / non-JSON / no usable content). A screenshot that cannot be fetched or exceeds
    the size cap simply comes back ``None`` while the markdown is still returned - a partial
    success, not a degrade.
    """
    formats: list[str] = ["markdown"] + (["screenshot@fullPage"] if want_screenshot else [])
    endpoint = f"{base_url.rstrip('/')}{_SCRAPE_PATH}"
    body: dict[str, Any] = {"url": url, "formats": formats, "onlyMainContent": False}
    try:
        resp = await http.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=_SCRAPE_TIMEOUT,
        )
    except Exception:  # transport error: degrade to the fallback fetcher (never crash)
        logger.info("firecrawl_degraded", reason="transport_error")
        return None
    if resp.status_code != 200:
        # A key/quota/URL problem: log the STATUS only (never the body - it could echo
        # the scraped page), and degrade. The Bearer key rides a header, never a URL.
        logger.info("firecrawl_degraded", reason="http_error", status=resp.status_code)
        return None
    try:
        payload = resp.json()
    except ValueError:
        logger.info("firecrawl_degraded", reason="non_json")
        return None
    if not isinstance(payload, dict):
        return None
    # v1 nests the result under ``data``; tolerate a flat shape too.
    raw = payload.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else payload

    md = data.get("markdown")
    markdown = md if isinstance(md, str) else ""
    screenshot_b64 = await _screenshot_b64(http, data) if want_screenshot else None

    if not markdown and screenshot_b64 is None:
        # Nothing usable came back -> let the caller fall back to the plain fetcher.
        logger.info("firecrawl_degraded", reason="empty_result")
        return None
    return FirecrawlPage(markdown=markdown, screenshot_b64=screenshot_b64)


async def _screenshot_b64(http: httpx.AsyncClient, data: dict[str, Any]) -> str | None:
    """Pull the screenshot out of a scrape result and normalise it to base64 PNG."""
    value = data.get("screenshot")
    if not isinstance(value, str) or not value.strip():
        return None
    return await _normalise_screenshot(http, value.strip())


async def _normalise_screenshot(http: httpx.AsyncClient, value: str) -> str | None:
    """Normalise a Firecrawl screenshot value (URL / data-URI / raw base64) to raw
    base64 PNG, or ``None`` when it is unfetchable or over the size cap."""
    if value.startswith("data:"):
        comma = value.find(",")
        return _bounded_b64(value[comma + 1 :]) if comma != -1 else None
    if value.startswith(("http://", "https://")):
        return await _fetch_png_b64(http, value)
    return _bounded_b64(value)  # already raw base64


def _bounded_b64(b64: str) -> str | None:
    """Return the base64 string iff its decoded size is within the cap, else ``None``."""
    b64 = b64.strip()
    if not b64:
        return None
    approx_bytes = len(b64) * 3 // 4  # base64 -> ~3 bytes per 4 chars
    return b64 if approx_bytes <= _MAX_SCREENSHOT_BYTES else None


async def _fetch_png_b64(http: httpx.AsyncClient, url: str) -> str | None:
    """Fetch a Firecrawl-hosted screenshot PNG and base64-encode it (bounded).

    The URL is Firecrawl's own storage (a trusted provider host, not user input), so it
    is fetched directly with redirects disabled + a bounded timeout; a non-200 or an
    over-cap body degrades to ``None`` (the markdown alone still drives the analysis)."""
    try:
        resp = await http.get(url, follow_redirects=False, timeout=_SCREENSHOT_TIMEOUT)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    content = resp.content
    if not content or len(content) > _MAX_SCREENSHOT_BYTES:
        return None
    return base64.b64encode(content).decode("ascii")


class FirecrawlClient:
    """Real ``Firecrawl`` over the shared async ``httpx.AsyncClient`` (Bearer-key auth).

    The key is resolved by the caller and passed here already extracted; it rides in the
    ``Authorization`` header (never a URL, never logged). A blank key raises
    ``ProviderNotConfiguredError`` naming the fix rather than calling unauthenticated."""

    provider = "firecrawl"

    def __init__(self, *, api_key: str, base_url: str = _DEFAULT_BASE_URL) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Firecrawl client unavailable: {_INSTALL_HINT}")
        self._api_key = api_key
        self._base_url = base_url or _DEFAULT_BASE_URL

    async def scrape(
        self, http: httpx.AsyncClient, url: str, *, want_screenshot: bool
    ) -> FirecrawlPage | None:
        return await firecrawl_scrape(
            http,
            api_key=self._api_key,
            base_url=self._base_url,
            url=url,
            want_screenshot=want_screenshot,
        )


@dataclass
class FakeFirecrawl:
    """Deterministic, offline ``Firecrawl`` for the endpoint + analysis unit tests.

    Returns ``page`` (a fixed :class:`FirecrawlPage`) or ``None`` to exercise the
    degrade/fallback path. Records the call count + the last ``want_screenshot`` so a
    test can prove the endpoint asked for a screenshot; honours ``want_screenshot=False``
    by dropping the screenshot. No network."""

    page: FirecrawlPage | None = field(
        default_factory=lambda: FirecrawlPage(
            markdown="# Rendered home\n\nWelcome to the real site.", screenshot_b64="ZmFrZS1wbmc="
        )
    )
    calls: int = 0
    last_want_screenshot: bool | None = None

    async def scrape(
        self, http: httpx.AsyncClient, url: str, *, want_screenshot: bool
    ) -> FirecrawlPage | None:
        self.calls += 1
        self.last_want_screenshot = want_screenshot
        if self.page is None:
            return None
        if not want_screenshot:
            return FirecrawlPage(markdown=self.page.markdown, screenshot_b64=None)
        return self.page


def firecrawl_from_settings(settings: Settings) -> Firecrawl | None:
    """A real ``FirecrawlClient`` when ``FIRECRAWL_API_KEY`` is present, else ``None``.

    Degrades to ``None`` (never raises) when the key is absent - the site-design endpoint
    then falls back to the plain-httpx fetcher (no screenshot). No secret is ever logged;
    the degraded path logs only the reason."""
    key = settings.firecrawl_api_key
    if not key:
        logger.info("firecrawl_degraded", reason="missing_key")
        return None
    try:
        return FirecrawlClient(
            api_key=key.get_secret_value(), base_url=settings.firecrawl_base_url
        )
    except ProviderNotConfiguredError as exc:
        logger.info("firecrawl_degraded", reason=str(exc))
        return None
