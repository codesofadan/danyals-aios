"""The sitemap size probe — what makes a deep audit's quote describe a real run.

`planned_pages` hands the engine a CEILING. The engine always stopped at whatever
a site actually had, so the committed cost was honest; the QUOTE was not, because
it named 300 pages for a 40-page site and the pre-flight gate reserved against
that. These tests pin the measurement, its bounds, and — the part that matters
most — the cases where it must answer "I could not tell" instead of a number.

Every test drives the REAL probe through `httpx.MockTransport`, so the redirect
following, the per-hop SSRF revalidation and the byte caps are exercised rather
than stubbed. The host is a PUBLIC IP LITERAL rather than a `.test` name because
`validate_public_host` performs real `getaddrinfo` before any transport is
consulted — a mock transport cannot bypass the guard, which is the point of it.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.security import PrivateAddressError
from app.services.site_size import SitemapSizeProbe

pytestmark = pytest.mark.unit


def _urlset(n: int, *, base: str = "http://93.184.216.34/p") -> bytes:
    locs = "".join(f"<url><loc>{base}{i}</loc></url>" for i in range(n))
    return f'<?xml version="1.0"?><urlset>{locs}</urlset>'.encode()


def _index(children: list[str]) -> bytes:
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return f'<?xml version="1.0"?><sitemapindex>{locs}</sitemapindex>'.encode()


def _probe(handler, **kw) -> SitemapSizeProbe:
    return SitemapSizeProbe(transport=httpx.MockTransport(handler), **kw)


def _routes(mapping: dict[str, httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        return mapping.get(str(request.url), httpx.Response(404))

    return handler


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #
def test_counts_a_plain_sitemap() -> None:
    size = _probe(_routes({
        "http://93.184.216.34/robots.txt": httpx.Response(404),
        "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=_urlset(42)),
    })).measure("http://93.184.216.34/some/page")
    assert size.pages == 42
    assert size.source == "sitemap"
    assert size.truncated is False


def test_follows_a_sitemap_index_and_sums_its_children() -> None:
    """An index's <loc>s are child SITEMAPS, not pages. Counting them as pages
    would report 2 for a 30-page site."""
    size = _probe(_routes({
        "http://93.184.216.34/robots.txt": httpx.Response(404),
        "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=_index(
            ["http://93.184.216.34/s1.xml", "http://93.184.216.34/s2.xml"]
        )),
        "http://93.184.216.34/s1.xml": httpx.Response(200, content=_urlset(20)),
        "http://93.184.216.34/s2.xml": httpx.Response(200, content=_urlset(10)),
    })).measure("http://93.184.216.34")
    assert size.pages == 30
    assert size.source == "sitemap_index"


def test_prefers_the_sitemap_robots_declares() -> None:
    """robots.txt is where a site SAYS its sitemap is; /sitemap.xml is only the
    convention. A site that declares a different location is not guessed at."""
    size = _probe(_routes({
        "http://93.184.216.34/robots.txt": httpx.Response(
            200, content=b"User-agent: *\nSitemap: http://93.184.216.34/custom-map.xml\n"
        ),
        "http://93.184.216.34/custom-map.xml": httpx.Response(200, content=_urlset(7)),
        "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=_urlset(9999)),
    })).measure("http://93.184.216.34")
    assert size.pages == 7
    assert size.source == "robots_sitemap"


def test_follows_redirects_manually() -> None:
    size = _probe(_routes({
        "http://93.184.216.34/robots.txt": httpx.Response(404),
        "http://93.184.216.34/sitemap.xml": httpx.Response(
            301, headers={"location": "http://93.184.216.34/real.xml"}
        ),
        "http://93.184.216.34/real.xml": httpx.Response(200, content=_urlset(5)),
    })).measure("http://93.184.216.34")
    assert size.pages == 5


# --------------------------------------------------------------------------- #
# "I could not tell" is an ANSWER, and it must never be zero
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("label", "routes"),
    [
        ("no sitemap at all", {"http://93.184.216.34/robots.txt": httpx.Response(404)}),
        ("sitemap 500s", {
            "http://93.184.216.34/robots.txt": httpx.Response(404),
            "http://93.184.216.34/sitemap.xml": httpx.Response(500),
        }),
        ("sitemap is empty", {
            "http://93.184.216.34/robots.txt": httpx.Response(404),
            "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=b"<urlset></urlset>"),
        }),
        ("sitemap is not xml", {
            "http://93.184.216.34/robots.txt": httpx.Response(404),
            "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=b"<html>nope</html>"),
        }),
    ],
)
def test_unknown_is_none_never_zero(label: str, routes: dict) -> None:
    """A zero would flow into `min()` and silently shrink a deep audit to nothing —
    an operator would pay a deep price to confirm a crawl of no pages. `None`
    forces every caller to decide what to do about not knowing."""
    size = _probe(_routes(routes)).measure("http://93.184.216.34")
    assert size.pages is None, label
    assert size.known is False
    assert size.source == "unknown"


def test_a_transport_failure_degrades_rather_than_raising() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    size = _probe(boom).measure("http://93.184.216.34")
    assert size.pages is None


def test_an_ssrf_hit_re_raises_and_is_not_reported_as_unknown() -> None:
    """The one failure that must NOT degrade. Quoting a run against a host the
    guard just refused would price work that can never legitimately run, and the
    operator would see a normal-looking estimate for it."""
    probe = _probe(_routes({}))
    with pytest.raises(PrivateAddressError):
        probe.measure("http://127.0.0.1/admin")


# --------------------------------------------------------------------------- #
# Bounds — this runs on a request path against a host we do not control
# --------------------------------------------------------------------------- #
def test_a_huge_index_is_capped_and_says_so() -> None:
    children = [f"http://93.184.216.34/s{i}.xml" for i in range(200)]
    routes = {
        "http://93.184.216.34/robots.txt": httpx.Response(404),
        "http://93.184.216.34/sitemap.xml": httpx.Response(200, content=_index(children)),
    }
    for c in children:
        routes[c] = httpx.Response(200, content=_urlset(10))
    size = _probe(_routes(routes)).measure("http://93.184.216.34")
    assert size.truncated is True
    # A truncated count is a FLOOR on the real total, not the total — and a caller
    # quoting from it is quoting low, which is why the flag is on the result.
    assert size.pages is not None and 0 < size.pages < 2000


def test_a_redirect_loop_terminates() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://93.184.216.34/sitemap.xml"})

    size = _probe(loop).measure("http://93.184.216.34")
    assert size.pages is None  # bounded, not hung
