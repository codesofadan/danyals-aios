"""XML sitemap + sitemap-index parser.

Handles plain sitemaps, sitemap indexes, gzipped sitemaps, and sitemap.xml.gz.
"""

from __future__ import annotations

import asyncio
import gzip
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

from lxml import etree

from audit_engine.crawlers.browser_client import CrawlerTransportError
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass
class SitemapURL:
    loc: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: float | None = None


@dataclass
class Sitemap:
    url: str
    status_code: int
    urls: list[SitemapURL] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)
    error: str | None = None


def _decode(content: bytes, content_type: str | None) -> str:
    if (content_type and "gzip" in content_type) or content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"gunzip failed: {e}") from e
    return content.decode("utf-8", errors="replace")


def parse(xml_text: str, url: str, status_code: int = 200) -> Sitemap:
    out = Sitemap(url=url, status_code=status_code)
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        out.error = f"XML parse: {e}"
        return out

    tag = etree.QName(root.tag).localname
    if tag == "sitemapindex":
        for sm in root.findall("sm:sitemap", NS):
            loc = sm.findtext("sm:loc", namespaces=NS)
            if loc:
                out.child_sitemaps.append(loc.strip())
    elif tag == "urlset":
        for u in root.findall("sm:url", NS):
            loc = u.findtext("sm:loc", namespaces=NS)
            if not loc:
                continue
            pri_text = u.findtext("sm:priority", namespaces=NS)
            priority = None
            if pri_text:
                try:
                    priority = float(pri_text)
                except ValueError:
                    pass
            out.urls.append(
                SitemapURL(
                    loc=loc.strip(),
                    lastmod=u.findtext("sm:lastmod", namespaces=NS),
                    changefreq=u.findtext("sm:changefreq", namespaces=NS),
                    priority=priority,
                )
            )
    else:
        out.error = f"unknown root element {tag}"
    return out


async def fetch_one(client: Any, url: str, *, retries: int = 2) -> Sitemap:
    """Fetch one sitemap URL with retry on transient transport errors and 5xx."""
    last_err: Exception | None = None
    resp = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            if 500 <= resp.status_code < 600 and attempt < retries:
                last_err = CrawlerTransportError(f"HTTP {resp.status_code}")
                resp = None
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            break
        except CrawlerTransportError as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
    if resp is None:
        log.warning(
            "sitemap_fetch_failed",
            url=url,
            error=type(last_err).__name__ if last_err else "unknown",
            attempts=retries + 1,
        )
        return Sitemap(url=url, status_code=0, error=str(last_err))

    if resp.status_code >= 400:
        return Sitemap(url=url, status_code=resp.status_code, error=f"HTTP {resp.status_code}")

    try:
        text = _decode(resp.content, resp.headers.get("content-type"))
    except ValueError as e:
        return Sitemap(url=url, status_code=resp.status_code, error=str(e))

    sm = parse(text, url, resp.status_code)
    return sm


async def fetch_all(
    client: Any,
    seeds: list[str],
    *,
    max_depth: int = 3,
    max_urls: int = 5000,
) -> list[Sitemap]:
    """Recursively fetch sitemap-indexes up to `max_depth`. Caps url collection
    at `max_urls` to avoid blowing memory on giant sites."""
    seen: set[str] = set()
    out: list[Sitemap] = []
    queue: list[tuple[str, int]] = [(s, 0) for s in seeds]

    total_urls = 0
    while queue and total_urls < max_urls:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        sm = await fetch_one(client, url)
        out.append(sm)
        total_urls += len(sm.urls)
        if depth < max_depth:
            for child in sm.child_sitemaps:
                if child not in seen:
                    queue.append((child, depth + 1))
    return out


def default_seeds(site_url: str) -> list[str]:
    """Common sitemap paths across major platforms (WordPress 5.5+, Yoast,
    Rank Math, Webflow, Shopify variants, hyphen variants, gz variants)."""
    base = site_url.rstrip("/") + "/"
    return [
        urljoin(base, "sitemap.xml"),
        urljoin(base, "sitemap_index.xml"),
        urljoin(base, "sitemap-index.xml"),
        urljoin(base, "wp-sitemap.xml"),
        urljoin(base, "sitemap.xml.gz"),
        urljoin(base, "sitemap_pages.xml"),
    ]
