"""Browser-impersonating crawler (curl_cffi). Sitemap-first, BFS fallback.

The crawler uses `BrowserClient` (curl_cffi-backed) instead of raw httpx so
the TLS fingerprint matches a real Chrome browser. This bypasses Cloudflare's
JA3/JA4 bot-detection layer, which previously caused 0 parsed pages on
~80% of sites with bot mitigation.

Phase 1A: no JS rendering. Phase 1B will add Playwright for the rendering
diff check (TECH-032 DOM rendered content comparison, TECH-031 CSR issues,
TECH-084 cloaking detection) and as a fallback when Cloudflare serves a JS
challenge that curl_cffi alone cannot solve.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from audit_engine.config import CrawlConfig
from audit_engine.crawlers.browser_client import BrowserClient, CrawlerTransportError
from audit_engine.logging_setup import get_logger
from audit_engine.parsers import html as html_parser
from audit_engine.parsers import robots as robots_parser
from audit_engine.parsers import sitemap as sitemap_parser
from audit_engine.security import is_public_url

log = get_logger(__name__)


def _is_public_or_drop(url: str) -> bool:
    """Defence-in-depth: drop URLs that resolve to internal/loopback hosts.

    Belt-and-braces companion to the CLI-level `_enforce_public_target`
    gate - catches sitemap entries and redirect targets pointing at
    169.254.169.254, localhost, RFC1918 ranges, etc., that an attacker
    might use to pivot via DNS rebinding or a 301 in the crawl path.
    """
    if is_public_url(url):
        return True
    log.warning("ssrf_guard_dropped_url", url=url)
    return False


@dataclass
class CrawledPage:
    url: str
    final_url: str
    http_status: int
    response_ms: int
    content_type: str | None
    bytes_size: int
    redirect_chain: list[str] = field(default_factory=list)
    html: str | None = None
    parsed: html_parser.ParsedHTML | None = None
    error: str | None = None
    http_version: str | None = None  # "HTTP/1.0", "HTTP/1.1", "HTTP/2", "HTTP/3"


@dataclass
class CrawlResult:
    site_url: str
    robots: robots_parser.RobotsTxt | None
    sitemaps: list[sitemap_parser.Sitemap]
    discovered_urls: list[str]
    pages: list[CrawledPage]
    duration_sec: float


def _is_same_site(url: str, site_url: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(site_url).netloc.lower()


async def _fetch_page(
    client: BrowserClient, url: str, *, parse_body: bool = True
) -> CrawledPage:
    start = time.monotonic()
    try:
        resp = await client.get(url)
    except CrawlerTransportError as e:
        return CrawledPage(
            url=url,
            final_url=url,
            http_status=0,
            response_ms=int((time.monotonic() - start) * 1000),
            content_type=None,
            bytes_size=0,
            error=f"{type(e).__name__}: {e}",
        )

    redirect_chain = [str(h.url) for h in resp.history] if resp.history else []
    ms = int((time.monotonic() - start) * 1000)
    ctype = resp.headers.get("content-type")
    body = resp.text if parse_body and ctype and "html" in ctype.lower() else None
    parsed = None
    if body:
        try:
            parsed = html_parser.parse(body, str(resp.url))
        except Exception as e:  # noqa: BLE001
            log.warning("html_parse_failed", url=url, error=type(e).__name__)

    return CrawledPage(
        url=url,
        final_url=str(resp.url),
        http_status=resp.status_code,
        response_ms=ms,
        content_type=ctype,
        bytes_size=len(resp.content),
        redirect_chain=redirect_chain,
        html=body,
        parsed=parsed,
        http_version=resp.http_version,
    )


async def discover_urls(
    client: BrowserClient,
    site_url: str,
    *,
    max_urls: int,
) -> tuple[robots_parser.RobotsTxt, list[sitemap_parser.Sitemap], list[str]]:
    """Discover candidate URLs via robots + sitemap, falling back to homepage
    link extraction if no sitemap is published."""
    robots = await robots_parser.fetch(client, site_url)
    seeds = robots.sitemaps or sitemap_parser.default_seeds(site_url)
    sitemaps = await sitemap_parser.fetch_all(client, seeds, max_urls=max_urls)

    urls: list[str] = []
    for sm in sitemaps:
        for u in sm.urls:
            urls.append(u.loc)

    # Dedup, prefer same-site, cap. Also drop any URL that resolves to a
    # private/loopback/link-local address (defence in depth against a
    # sitemap entry that points at an internal host).
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u in seen or not _is_same_site(u, site_url):
            continue
        if not _is_public_or_drop(u):
            continue
        seen.add(u)
        deduped.append(u)
        if len(deduped) >= max_urls:
            break

    if not deduped:
        # No sitemap — fetch homepage and harvest internal links. Retry the
        # homepage fetch up to 2 times because Cloudflare's first-hit JS
        # challenge often kills the cold connection. If the static fetch still
        # yields zero internal links (typical for SPAs whose nav is built
        # client-side), fall back to a Playwright-rendered link harvest.
        log.info("no_sitemap_falling_back_to_homepage_links", site=site_url)
        home = await _fetch_homepage_with_retry(client, site_url, retries=2)

        if home is None or home.error or not home.parsed:
            log.warning(
                "homepage_fallback_fetch_failed",
                site=site_url,
                http_status=getattr(home, "http_status", None),
                error=getattr(home, "error", None),
            )
            rendered = await _render_homepage_links(site_url, max_urls=max_urls)
            for href in rendered:
                if (
                    href not in seen
                    and _is_same_site(href, site_url)
                    and _is_public_or_drop(href)
                ):
                    seen.add(href)
                    deduped.append(href)
                    if len(deduped) >= max_urls:
                        break
        else:
            internal = [link for link in home.parsed.links if link.is_internal]
            for link in internal:
                if link.href not in seen and _is_public_or_drop(link.href):
                    seen.add(link.href)
                    deduped.append(link.href)
                    if len(deduped) >= max_urls:
                        break
            if not internal:
                log.warning(
                    "homepage_fallback_no_internal_links",
                    site=site_url,
                    total_links=len(home.parsed.links),
                )
                rendered = await _render_homepage_links(site_url, max_urls=max_urls)
                for href in rendered:
                    if (
                        href not in seen
                        and _is_same_site(href, site_url)
                        and _is_public_or_drop(href)
                    ):
                        seen.add(href)
                        deduped.append(href)
                        if len(deduped) >= max_urls:
                            break

    # Always include the homepage explicitly.
    if site_url not in seen:
        deduped.insert(0, site_url)

    return robots, sitemaps, deduped[:max_urls]


async def _fetch_homepage_with_retry(
    client: BrowserClient, site_url: str, *, retries: int = 2
) -> CrawledPage | None:
    last: CrawledPage | None = None
    for attempt in range(retries + 1):
        page = await _fetch_page(client, site_url)
        last = page
        if page.parsed and page.http_status and page.http_status < 400:
            return page
        if attempt < retries:
            await asyncio.sleep(0.5 * (2 ** attempt))
    return last


async def _render_homepage_links(site_url: str, *, max_urls: int) -> list[str]:
    """Last-ditch Playwright render to harvest <a href> for SPAs whose static
    HTML has no navigation. Best-effort: any failure returns an empty list."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("playwright_unavailable_skipping_render_fallback")
        return []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto(site_url, wait_until="domcontentloaded", timeout=20000)
            hrefs = await page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
            await browser.close()
        log.info("playwright_render_fallback_ok", site=site_url, links=len(hrefs))
        return hrefs[: max_urls * 2]
    except Exception as e:  # noqa: BLE001
        log.warning("playwright_render_failed", site=site_url, error=type(e).__name__)
        return []


async def crawl(
    site_url: str,
    *,
    config: CrawlConfig | None = None,
    max_pages: int | None = None,
) -> CrawlResult:
    cfg = config or CrawlConfig()
    cap = max_pages if max_pages is not None else cfg.max_pages_quick
    start = time.monotonic()

    site_url = site_url.rstrip("/")
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url

    async with BrowserClient(
        timeout=cfg.request_timeout_sec,
        follow_redirects=cfg.follow_redirects,
        max_redirects=cfg.max_redirects,
    ) as client:
        robots, sitemaps, urls = await discover_urls(client, site_url, max_urls=cap)
        log.info(
            "crawl_discovery_complete",
            site=site_url,
            sitemaps=len(sitemaps),
            urls_discovered=len(urls),
        )

        sem = asyncio.Semaphore(cfg.max_concurrent)

        async def _bounded(url: str) -> CrawledPage:
            async with sem:
                # Robots gate per-URL (signal only; we still fetch).
                if cfg.respect_robots and robots and not robots.is_allowed(
                    urlparse(url).path or "/", "*"
                ):
                    log.info("robots_disallow", url=url)
                return await _fetch_page(client, url)

        pages = await asyncio.gather(*[_bounded(u) for u in urls])

    duration = time.monotonic() - start
    log.info(
        "crawl_complete",
        site=site_url,
        pages=len(pages),
        duration_sec=round(duration, 2),
    )
    return CrawlResult(
        site_url=site_url,
        robots=robots,
        sitemaps=sitemaps,
        discovered_urls=urls,
        pages=pages,
        duration_sec=duration,
    )
