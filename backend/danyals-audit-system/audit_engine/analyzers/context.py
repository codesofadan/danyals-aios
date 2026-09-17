"""The crawl graph, derived once.

Every site-wide analyzer used to rebuild the link graph itself, each with its
own URL handling, which is why their verdicts disagreed: one reported a page as
an orphan while another counted an inbound link to it. This builds the graph a
single time, through the single normalisation in ``urls.py``, and hands the
same object to every check that needs it.

Eight of Wave 3's checks depend on this, and so does any honest definition of
"orphan", "click depth" or "internal link".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from audit_engine.analyzers.urls import (
    DEFAULT_POLICY,
    NormalisationPolicy,
    is_internal,
    normalise,
    registrable_host,
)

#: Depth reported for a page nothing links to. Larger than any real depth, and
#: deliberately not ``None`` so comparisons never blow up in a check.
UNREACHABLE = 10_000


@dataclass
class CrawlContext:
    """Everything a site-wide check needs, computed once.

    Every URL key in every mapping is normalised. Never index these with a raw
    href - use :meth:`key`.
    """

    site_url: str
    policy: NormalisationPolicy = DEFAULT_POLICY

    #: normalised url -> the crawled page
    by_url: dict[str, Any] = field(default_factory=dict)
    #: normalised url -> normalised internal targets it links to
    outbound: dict[str, set[str]] = field(default_factory=dict)
    #: normalised url -> normalised internal pages that link to it
    inbound: dict[str, set[str]] = field(default_factory=dict)
    #: normalised url -> clicks from the homepage; UNREACHABLE if never linked
    depth: dict[str, int] = field(default_factory=dict)
    #: every normalised url listed in a sitemap
    sitemap_urls: set[str] = field(default_factory=set)
    #: every normalised url actually fetched
    crawled_urls: set[str] = field(default_factory=set)
    #: every normalised url discovered by any means
    discovered_urls: set[str] = field(default_factory=set)
    #: normalised external hosts linked to, with a count
    external_hosts: dict[str, int] = field(default_factory=dict)
    #: the parsed robots.txt, when one was fetched
    robots: Any | None = None
    #: the Sitemap objects as parsed, including any that failed to parse
    sitemaps: list[Any] = field(default_factory=list)
    #: every URL as the crawler requested it, before normalisation. by_url is
    #: keyed on the NORMALISED form, so anything looking for two URLs that mean
    #: one page must read this instead.
    raw_urls: list[str] = field(default_factory=list)

    # -- lookups ------------------------------------------------------------

    def key(self, url: str, *, base: str | None = None) -> str:
        """Normalise ``url``, resolving it against ``base`` when relative."""
        if base and not url.lower().startswith(("http://", "https://")):
            try:
                url = urljoin(base, url)
            except ValueError:
                return ""
        return normalise(url, policy=self.policy)

    def page(self, url: str) -> Any | None:
        return self.by_url.get(self.key(url))

    @property
    def home(self) -> str:
        return self.key(self.site_url)

    def depth_of(self, url: str) -> int:
        return self.depth.get(self.key(url), UNREACHABLE)

    def inbound_count(self, url: str) -> int:
        return len(self.inbound.get(self.key(url), ()))

    @property
    def is_partial(self) -> bool:
        """True when the crawl saw less than the site it discovered.

        Reachability is only meaningful over a COMPLETE crawl. On a truncated
        one, a page looks orphaned or unreachable simply because the page that
        links to it was never fetched. Reporting that to a client as "6 of your
        8 pages are unreachable" is a measurement of our own page cap, not of
        their site.
        """
        known = self.discovered_urls | self.sitemap_urls
        return bool(known - self.crawled_urls)

    @property
    def coverage(self) -> float:
        """Share of known URLs that were actually fetched."""
        known = self.discovered_urls | self.sitemap_urls
        return len(self.crawled_urls) / len(known) if known else 1.0

    # -- derived sets --------------------------------------------------------

    def orphans(self) -> set[str]:
        """Crawled pages with no internal link pointing at them.

        The homepage is never an orphan: it is the entry point, so "nothing
        links to it" is expected rather than a defect.
        """
        home = self.home
        return {u for u in self.crawled_urls if u != home and not self.inbound.get(u)}

    def unreachable(self) -> set[str]:
        """Crawled pages not reachable by following links from the homepage.

        Distinct from :meth:`orphans`: a page can have an inbound link from
        another unreachable page and still never be found from the homepage.
        """
        return {u for u in self.crawled_urls if self.depth.get(u, UNREACHABLE) >= UNREACHABLE}

    def in_sitemap_not_crawled(self) -> set[str]:
        return self.sitemap_urls - self.crawled_urls

    def crawled_not_in_sitemap(self) -> set[str]:
        return self.crawled_urls - self.sitemap_urls


def build_context(
    crawl_result: Any, *, policy: NormalisationPolicy = DEFAULT_POLICY
) -> CrawlContext:
    """Derive the graph from a ``CrawlResult``. Total: never raises."""
    site_url = getattr(crawl_result, "site_url", "") or ""
    ctx = CrawlContext(site_url=site_url, policy=policy)

    pages = list(getattr(crawl_result, "pages", []) or [])
    for cp in pages:
        # A redirect means the CONTENT lives at final_url; index it there so a
        # link to either form resolves to one page.
        raw = getattr(cp, "final_url", None) or getattr(cp, "url", "") or ""
        k = ctx.key(raw)
        if not k:
            continue
        ctx.by_url[k] = cp
        ctx.crawled_urls.add(k)
        raw_requested = getattr(cp, "url", "") or raw
        if raw_requested:
            ctx.raw_urls.append(raw_requested)
        ctx.outbound.setdefault(k, set())
        ctx.inbound.setdefault(k, set())
        # the pre-redirect URL must also resolve to this page
        orig = ctx.key(getattr(cp, "url", "") or "")
        if orig and orig != k:
            ctx.by_url.setdefault(orig, cp)

    for cp in pages:
        raw = getattr(cp, "final_url", None) or getattr(cp, "url", "") or ""
        src = ctx.key(raw)
        parsed = getattr(cp, "parsed", None)
        if not src or parsed is None:
            continue
        for link in getattr(parsed, "links", []) or []:
            href = getattr(link, "href", "") or ""
            if not href or href.startswith("#"):
                continue
            if not is_internal(href, site_url):
                h = registrable_host(href)
                if h:
                    ctx.external_hosts[h] = ctx.external_hosts.get(h, 0) + 1
                continue
            dst = ctx.key(href, base=raw)
            if not dst or dst == src:
                continue
            ctx.outbound.setdefault(src, set()).add(dst)
            ctx.inbound.setdefault(dst, set()).add(src)
            ctx.discovered_urls.add(dst)

    for u in getattr(crawl_result, "discovered_urls", []) or []:
        k = ctx.key(u)
        if k:
            ctx.discovered_urls.add(k)
    ctx.discovered_urls |= ctx.crawled_urls

    for sm in getattr(crawl_result, "sitemaps", []) or []:
        for entry in getattr(sm, "urls", []) or []:
            loc = entry if isinstance(entry, str) else getattr(entry, "loc", "")
            k = ctx.key(loc or "")
            if k:
                ctx.sitemap_urls.add(k)

    ctx.robots = getattr(crawl_result, "robots", None)
    ctx.sitemaps = list(getattr(crawl_result, "sitemaps", []) or [])
    ctx.depth = _bfs_depth(ctx)
    return ctx


def _bfs_depth(ctx: CrawlContext) -> dict[str, int]:
    """Clicks from the homepage. Breadth-first, so the FIRST time a page is
    reached is its shortest path - which is what "click depth" means."""
    home = ctx.home
    if not home or home not in ctx.crawled_urls:
        # No homepage in the crawl means no anchor for "clicks from the home
        # page". Claiming depth 0 for a page we never fetched would be a
        # measurement we did not take.
        return {}
    depth = {home: 0}
    queue: deque[str] = deque([home])
    while queue:
        cur = queue.popleft()
        for nxt in ctx.outbound.get(cur, ()):
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                queue.append(nxt)
    return depth
