"""Measure how many pages a site actually has, so a deep audit is quoted for the
run it will really make.

WHY THIS EXISTS. ``audit_depth.planned_pages`` hands the engine a CEILING - 300
for a deep run. The engine stops at whatever the site actually has, so the
committed cost was always honest. The QUOTE was not: an operator confirming a
deep audit on a 40-page site was shown a 300-page price, and the pre-flight gate
reserved budget against that inflated figure. It erred high, which is the safe
direction, but it is still a number that describes no run - and the recovery plan
(§3.2) asks for a deep tier *"scaled to actual site size"*.

WHAT IT COSTS. Nothing metered. A site's own ``robots.txt`` and ``sitemap.xml``
are public, free, and exactly the inventory this question wants. No paid
provider is involved, which is why this can run on the quote path at all.

WHAT IT IS NOT. Not a crawl, and not authoritative. A sitemap can be absent,
stale, partial, or a deliberate subset. So this returns a MEASUREMENT WITH ITS
PROVENANCE (:class:`SiteSize`), never a bare number, and ``pages is None`` -
"could not tell" - is a first-class outcome that callers must handle rather than
a zero they might arithmetic with.

SSRF. ``app/core/security``'s caller contract is explicit that one-shot
validation is insufficient: httpx re-resolves DNS and a 30x can bounce to
169.254.169.254. Redirects are therefore disabled and every hop is re-validated,
the same pattern as ``services/policy_watch.SsrfGuardedPolicyFetcher``. A guard
hit RE-RAISES (the caller must not silently treat a blocked host as "unknown
size"); every transport failure degrades to unknown.

BOUNDED IN EVERY DIRECTION, because this runs on a request path against a host we
do not control: a byte cap per document, a cap on redirect hops, a cap on how
many child sitemaps an index is followed into, and a whole-probe deadline. A
hostile or broken sitemap costs a bounded amount of time and memory, never an
unbounded one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx

from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger

logger = get_logger("services.site_size")

SizeSource = Literal["sitemap", "sitemap_index", "robots_sitemap", "unknown"]

# Every bound this probe operates under, in one place so they can be read at once.
_MAX_BODY_BYTES = 5_000_000  # one sitemap document; larger is truncated, not fetched whole
_MAX_REDIRECT_HOPS = 5
_MAX_CHILD_SITEMAPS = 25  # an index may list thousands; we sample a bounded prefix
_MAX_ROBOTS_BYTES = 100_000
_DEFAULT_TIMEOUT = 8.0  # per request
_DEFAULT_DEADLINE = 20.0  # whole probe, across every request it makes

# `<loc>` is the only element that matters for counting, in both a urlset and a
# sitemapindex. Parsed by regex rather than an XML parser ON PURPOSE: this input is
# attacker-influenced, and Python's stdlib XML parsers have documented entity-
# expansion and external-entity exposure. Counting `<loc>` needs no tree.
_LOC_RE = re.compile(rb"<loc>\s*([^<\s][^<]*?)\s*</loc>", re.IGNORECASE)
_SITEMAPINDEX_RE = re.compile(rb"<sitemapindex", re.IGNORECASE)
_ROBOTS_SITEMAP_RE = re.compile(rb"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class SiteSize:
    """A page-count measurement and where it came from.

    ``pages is None`` means UNKNOWN - the probe could not establish a count. That
    is deliberately not ``0``: a zero would flow into ``min()`` and silently
    shrink a deep audit to nothing, which is exactly the class of bug this module
    exists to avoid.
    """

    pages: int | None
    source: SizeSource
    # True when a bound stopped us short, so `pages` is a FLOOR on the real total
    # rather than the total. A caller quoting from a truncated count is quoting
    # low, and should say so.
    truncated: bool = False
    detail: str = ""

    @property
    def known(self) -> bool:
        return self.pages is not None


UNKNOWN = SiteSize(pages=None, source="unknown")


def _origin(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc or parsed.path}"


class SitemapSizeProbe:
    """Count a site's pages from its sitemaps. Blocking; call off the event loop.

    ``validate_public_host`` blocks on DNS and httpx here is synchronous, so an
    async caller MUST use ``asyncio.to_thread`` - the same contract every other
    guarded fetch path in this tree follows.
    """

    def __init__(
        self,
        *,
        user_agent: str = "AIOSAuditSizer/1.0",
        timeout: float = _DEFAULT_TIMEOUT,
        deadline: float = _DEFAULT_DEADLINE,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._deadline = deadline
        # A test supplies an ``httpx.MockTransport`` here so the suite exercises the
        # REAL redirect-following, hop-revalidating, byte-capping code path against
        # canned responses, rather than a stand-in for it. Production passes None.
        self._transport = transport

    # -- transport ---------------------------------------------------------- #
    def _get(self, client: httpx.Client, url: str, *, max_bytes: int) -> bytes | None:
        """One guarded GET, following redirects MANUALLY so each hop is re-validated."""
        current = url
        for _hop in range(_MAX_REDIRECT_HOPS):
            validate_public_host(current)  # every hop, not just the first
            resp = client.get(current)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if resp.status_code != 200:
                return None
            return bytes(resp.content)[:max_bytes]
        return None

    # -- probe -------------------------------------------------------------- #
    def measure(self, url: str) -> SiteSize:
        """Best-effort page count for ``url``'s origin. Never raises except SSRF."""
        origin = _origin(url)
        started = time.monotonic()

        def out_of_time() -> bool:
            return (time.monotonic() - started) > self._deadline

        try:
            with httpx.Client(
                follow_redirects=False,  # followed manually; see _get
                timeout=httpx.Timeout(self._timeout),
                headers={"User-Agent": self._ua},
                transport=self._transport,
            ) as client:
                candidates, discovered = self._discover(client, origin)
                source: SizeSource = discovered
                if not candidates:
                    return SiteSize(None, "unknown", detail="no sitemap found")

                total = 0
                truncated = False
                seen: set[str] = set()
                queue = list(candidates)
                fetched = 0

                while queue and not out_of_time():
                    if fetched >= _MAX_CHILD_SITEMAPS:
                        truncated = True
                        break
                    target = queue.pop(0)
                    if target in seen:
                        continue
                    seen.add(target)
                    body = self._get(client, target, max_bytes=_MAX_BODY_BYTES)
                    fetched += 1
                    if body is None:
                        continue
                    locs = _LOC_RE.findall(body)
                    if _SITEMAPINDEX_RE.search(body):
                        # An index: its <loc>s are child SITEMAPS, not pages.
                        for raw in locs:
                            child = raw.decode("utf-8", "ignore").strip()
                            if child and child not in seen:
                                queue.append(child)
                        source = "sitemap_index"
                    else:
                        total += len(locs)

                if queue and not truncated:
                    truncated = True  # we ran out of deadline with work left

                if total == 0:
                    return SiteSize(None, "unknown", detail="sitemap listed no pages")
                return SiteSize(total, source, truncated=truncated)
        except PrivateAddressError:
            # Never degraded to "unknown": a caller must not quote a run against a
            # host the SSRF guard just refused.
            logger.warning("site_size_ssrf_blocked", url=str(url).split("?", 1)[0])
            raise
        except Exception:
            logger.info("site_size_probe_failed", url=str(url).split("?", 1)[0])
            return SiteSize(None, "unknown", detail="probe failed")

    def _discover(self, client: httpx.Client, origin: str) -> tuple[list[str], SizeSource]:
        """Sitemap URLs for an origin: robots.txt first (the declared location),
        then the conventional /sitemap.xml."""
        try:
            robots = self._get(client, f"{origin}/robots.txt", max_bytes=_MAX_ROBOTS_BYTES)
        except PrivateAddressError:
            raise
        except Exception:
            robots = None
        if robots:
            declared = [
                m.decode("utf-8", "ignore").strip() for m in _ROBOTS_SITEMAP_RE.findall(robots)
            ]
            declared = [d for d in declared if d]
            if declared:
                return declared[:_MAX_CHILD_SITEMAPS], "robots_sitemap"
        return [f"{origin}/sitemap.xml"], "sitemap"
