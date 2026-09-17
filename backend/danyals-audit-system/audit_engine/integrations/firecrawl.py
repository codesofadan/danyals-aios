"""Firecrawl: the page as a browser renders it.

The engine's own crawler uses ``curl_cffi`` and executes no JavaScript, so what
it fetches is exactly what Googlebot's FIRST pass sees. Comparing that against a
rendered DOM is the only way to answer the questions Wave 6 exists for: is the
content JavaScript-injected, does the H1 exist before render, is the page
readable at all without scripts.

**``rawHtml``, not ``html``.** Firecrawl's ``html`` output is CLEANED - measured
against smileon.pk it stripped the ``<title>`` and all six JSON-LD blocks. Using
it as "the rendered DOM" would report "no structured data after rendering" on a
page carrying six schema blocks. ``rawHtml`` is the unprocessed post-render
document and parses faithfully.

Rendering consumes a metered monthly allowance, which is why ``rendered_html``
is classed ``free_quota`` rather than ``zero``: a free lead-magnet audit must
not silently burn the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger
from audit_engine.security import PrivateAddressError, validate_public_host

log = get_logger(__name__)

FIRECRAWL_API = "https://api.firecrawl.dev/v1"

#: Rendering is slow by nature - a real browser, a real network. Past this the
#: page is not worth waiting for and the audit should carry on without it.
RENDER_TIMEOUT_MS = 45_000


@dataclass(frozen=True)
class RenderResult:
    """One rendered page, or the reason there isn't one."""

    url: str
    #: The post-JavaScript document, unprocessed. Empty when the render failed.
    rendered_html: str = ""
    status_code: int | None = None
    title: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.rendered_html) and not self.error


class FirecrawlClient(BaseClient):
    """Scrape one URL with JavaScript executed."""

    provider_name = "firecrawl"
    base_url = FIRECRAWL_API

    def __init__(self, *, api_key: str | None = None, timeout: float = 90.0) -> None:
        super().__init__(timeout=timeout, max_retries=2)
        self._api_key = api_key

    async def render(self, url: str) -> RenderResult:
        """The page after JavaScript. Never raises: a failed render is a
        finding about the run, not a reason to lose the audit."""
        if not self._api_key:
            return RenderResult(url=url, error="no FIRECRAWL_API_KEY configured")
        try:
            validate_public_host(url)
        except (PrivateAddressError, ValueError) as e:
            # Rendering follows redirects inside a real browser, so the SSRF
            # guard matters as much here as on a direct probe.
            return RenderResult(url=url, error=f"refused: {e}")

        body: dict[str, Any] = {
            # rawHtml only: `html` is Firecrawl's CLEANED output and drops the
            # title and JSON-LD, which would make every schema check lie.
            "url": url,
            "formats": ["rawHtml"],
            "onlyMainContent": False,
            "timeout": RENDER_TIMEOUT_MS,
        }
        try:
            resp = await self.post(
                "/scrape",
                json_body=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            payload = resp.json()
        except Exception as e:
            log.warning("firecrawl_render_failed", url=url, error=type(e).__name__)
            return RenderResult(url=url, error=f"{type(e).__name__}: {str(e)[:160]}")

        if not payload.get("success"):
            return RenderResult(
                url=url, error=str(payload.get("error") or "firecrawl reported failure")[:160]
            )
        data = payload.get("data") or {}
        meta = data.get("metadata") or {}
        return RenderResult(
            url=url,
            rendered_html=data.get("rawHtml") or "",
            status_code=meta.get("statusCode"),
            title=meta.get("title"),
        )
