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

import asyncio
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

#: How many times a 429 is retried before the capture degrades, and how long to wait.
#: Small on purpose: a design capture sits inside a request an operator is waiting on, so
#: the ceiling on total added latency is a few seconds, not a resilient-queue's minutes.
_RATE_LIMIT_ATTEMPTS = 3
_RATE_LIMIT_BACKOFF = 2.0      # seconds, doubled per attempt
_RATE_LIMIT_MAX_SLEEP = 15.0   # never wait longer than this on one attempt

#: Anthropic's HARD per-dimension limit for an image block. Exceed it on either axis and
#: the Messages API answers `400 invalid_request_error: At least one of the image
#: dimensions exceed max allowed size: 8000 pixels` - it does not downscale for you.
#:
#: MEASURED DEFECT (2026-09-25). The byte cap above was the only guard, and it does not
#: catch this: a real capture of https://app.smarthealth.ae came back 1.3 MB - comfortably
#: inside the 4 MB cap - and over 8000 px TALL, because `screenshot@fullPage` renders the
#: entire page top-to-bottom. The vision call 400'd, `extract_site_design` caught it as
#: `analysis_failed`, and the whole design capture degraded with NOTHING saved. Every
#: reasonably long page hit this, which is most real sites.
_MAX_SCREENSHOT_EDGE = 8000

#: PNG magic + the fixed offsets of IHDR's width/height (big-endian uint32 each).
#: Read from the header rather than with an imaging library on purpose: the backend
#: declares no image dependency, and 24 bytes of a documented file format is a smaller
#: commitment than adding Pillow to read two integers.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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
    page = await _scrape_once(
        http, api_key=api_key, base_url=base_url, url=url,
        want_screenshot=want_screenshot, full_page=True,
    )
    # A FULL-PAGE capture of a long page routinely exceeds the vision API's 8000 px
    # per-dimension limit, and `_fetch_png_b64` drops it for that reason. Retrying with
    # the VIEWPORT format keeps vision rather than silently falling back to text-only:
    # above the fold is where the palette, the type scale, the button and card styling
    # actually live, so a clipped screenshot is far better evidence than none. Only the
    # tall pages pay the extra render.
    if want_screenshot and page is not None and page.screenshot_b64 is None:
        logger.info("firecrawl_screenshot_retry", reason="fullpage_unusable", url_host=_host(url))
        viewport = await _scrape_once(
            http, api_key=api_key, base_url=base_url, url=url,
            want_screenshot=True, full_page=False,
        )
        if viewport is not None and viewport.screenshot_b64 is not None:
            # Keep the FULL-PAGE markdown (it covers the whole document) and take only
            # the usable screenshot from the retry.
            return FirecrawlPage(
                markdown=page.markdown or viewport.markdown,
                screenshot_b64=viewport.screenshot_b64,
            )
    return page


def _host(url: str) -> str:
    """The URL's host, for logs that must never echo a full scraped URL."""
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


async def _scrape_once(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    base_url: str,
    url: str,
    want_screenshot: bool,
    full_page: bool,
) -> FirecrawlPage | None:
    """One Firecrawl scrape. ``full_page`` picks the screenshot variant."""
    shot = "screenshot@fullPage" if full_page else "screenshot"
    formats: list[str] = ["markdown"] + ([shot] if want_screenshot else [])
    endpoint = f"{base_url.rstrip('/')}{_SCRAPE_PATH}"
    body: dict[str, Any] = {"url": url, "formats": formats, "onlyMainContent": False}
    resp = None
    # RATE LIMITING IS TRANSIENT, AND THIS SEAM USED TO TREAT IT AS FATAL.
    #
    # A 429 fell into the generic non-200 branch below: log the status, return None,
    # degrade to the plain fetcher. For ONE operator-triggered capture that is barely
    # visible. MEASURED on a 45-page sweep (2026-09-25): 36 of 45 captures degraded on
    # 429, so a bulk design capture - which is exactly what an agency onboarding a client
    # runs - would have silently produced text-only profiles for most of the batch and
    # reported nothing wrong. The oversize retry above makes it worse by design: a tall
    # page costs two calls, so the batch hits the limit sooner.
    #
    # Bounded, and honest about the wait: `Retry-After` is obeyed when the provider sends
    # it, otherwise a short exponential backoff. Exhausting the attempts still degrades
    # rather than raising, which is this module's contract.
    for attempt in range(_RATE_LIMIT_ATTEMPTS):
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
        if resp.status_code != 429:
            break
        if attempt == _RATE_LIMIT_ATTEMPTS - 1:
            logger.info("firecrawl_degraded", reason="rate_limited", attempts=attempt + 1)
            return None
        delay = _retry_after_seconds(resp) or _RATE_LIMIT_BACKOFF * (2**attempt)
        logger.info("firecrawl_rate_limited", attempt=attempt + 1, sleeping=round(delay, 1))
        await asyncio.sleep(min(delay, _RATE_LIMIT_MAX_SLEEP))
    if resp is None:  # pragma: no cover - the loop always assigns or returns
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


def _retry_after_seconds(resp: Any) -> float | None:
    """The provider's ``Retry-After`` in seconds, when it sent a usable one.

    Only the delta-seconds form is honoured. The HTTP-date form is legal but rare here,
    and mis-parsing a date into a multi-hour sleep inside a request an operator is
    waiting on is worse than falling back to the local backoff.
    """
    raw = ""
    try:
        raw = str(resp.headers.get("retry-after") or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


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


def png_dimensions(raw: bytes) -> tuple[int, int] | None:
    """``(width, height)`` of a PNG read from its IHDR header, or ``None``.

    Stdlib only. A non-PNG or a truncated header returns ``None``, which callers treat
    as "dimensions unknown" and let through - the byte cap and the API itself are still
    behind it, so an unreadable header degrades to the previous behaviour rather than
    dropping a screenshot that might be fine.
    """
    if len(raw) < 24 or not raw.startswith(_PNG_MAGIC) or raw[12:16] != b"IHDR":
        return None
    return (
        int.from_bytes(raw[16:20], "big"),
        int.from_bytes(raw[20:24], "big"),
    )


def screenshot_is_oversized(raw: bytes) -> bool:
    """Whether this PNG would be REFUSED by the vision API for its dimensions.

    Separate from the byte cap because they catch different failures: bytes bound what
    the prompt costs, dimensions bound what the API will accept at all. A tall full-page
    capture routinely passes the first and fails the second.
    """
    dims = png_dimensions(raw)
    return dims is not None and max(dims) > _MAX_SCREENSHOT_EDGE


def _bounded_b64(b64: str) -> str | None:
    """Return the base64 string iff it is within BOTH caps (bytes and dimensions)."""
    b64 = b64.strip()
    if not b64:
        return None
    approx_bytes = len(b64) * 3 // 4  # base64 -> ~3 bytes per 4 chars
    if approx_bytes > _MAX_SCREENSHOT_BYTES:
        return None
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    if screenshot_is_oversized(raw):
        logger.info("firecrawl_screenshot_oversized", dimensions=str(png_dimensions(raw)))
        return None
    return b64


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
    if screenshot_is_oversized(content):
        # The caller retries with the VIEWPORT format rather than losing vision entirely.
        logger.info("firecrawl_screenshot_oversized", dimensions=str(png_dimensions(content)))
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
