"""The crawl graph, built once, must agree with itself.

Site-wide analyzers used to derive this ad hoc, so one could call a page an
orphan while another counted an inbound link to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers.context import UNREACHABLE, build_context


@dataclass
class FakeLink:
    href: str


@dataclass
class FakeParsed:
    links: list[FakeLink] = field(default_factory=list)


@dataclass
class FakePage:
    url: str
    final_url: str | None = None
    parsed: FakeParsed | None = None

    def __post_init__(self):
        if self.final_url is None:
            self.final_url = self.url


@dataclass
class FakeSitemap:
    urls: list[str] = field(default_factory=list)


@dataclass
class FakeCrawl:
    site_url: str
    pages: list[FakePage] = field(default_factory=list)
    sitemaps: list[FakeSitemap] = field(default_factory=list)
    discovered_urls: list[str] = field(default_factory=list)


S = "https://example.com/"


def page(path, links=()):
    return FakePage(url=f"https://example.com{path}",
                    parsed=FakeParsed([FakeLink(h) for h in links]))


@pytest.fixture
def ctx():
    #  /  ->  /a  ->  /b  ->  /c        /orphan is crawled, nothing links to it
    #  /  ->  /a  (via a relative href and a trailing-slash variant too)
    return build_context(FakeCrawl(
        site_url=S,
        pages=[
            page("/", ["/a", "a/", "https://other.com/x", "mailto:z@y.com"]),
            page("/a", ["/b", "../a"]),
            page("/b", ["/c"]),
            page("/c", []),
            page("/orphan", []),
        ],
        sitemaps=[FakeSitemap(["https://example.com/", "https://example.com/a",
                              "https://example.com/never-crawled"])],
    ))


def test_every_key_is_normalised(ctx):
    assert "https://example.com/a" in ctx.by_url
    # the trailing-slash variant of the same link did not create a second node
    assert "https://example.com/a/" not in ctx.by_url


def test_click_depth_is_the_shortest_path(ctx):
    assert ctx.depth_of("https://example.com/") == 0
    assert ctx.depth_of("https://example.com/a") == 1
    assert ctx.depth_of("https://example.com/b") == 2
    assert ctx.depth_of("https://example.com/c") == 3


def test_a_page_nothing_links_to_is_unreachable_not_depth_zero(ctx):
    assert ctx.depth_of("https://example.com/orphan") == UNREACHABLE
    assert ctx.unreachable() == {"https://example.com/orphan"}


def test_orphans_exclude_the_homepage(ctx):
    """Nothing links to the homepage; that is not a defect."""
    assert ctx.orphans() == {"https://example.com/orphan"}


def test_a_relative_href_resolves_against_its_page(ctx):
    assert "https://example.com/a" in ctx.outbound["https://example.com/"]


def test_inbound_is_the_exact_reverse_of_outbound(ctx):
    for src, dsts in ctx.outbound.items():
        for dst in dsts:
            assert src in ctx.inbound[dst], f"{src} -> {dst} missing from inbound"
    for dst, srcs in ctx.inbound.items():
        for src in srcs:
            assert dst in ctx.outbound[src]


def test_self_links_are_not_edges(ctx):
    for src, dsts in ctx.outbound.items():
        assert src not in dsts


def test_external_links_are_counted_by_host_not_followed(ctx):
    assert ctx.external_hosts == {"other.com": 1}
    assert "https://other.com/x" not in ctx.by_url


def test_mailto_is_neither_internal_nor_an_external_host(ctx):
    assert "y.com" not in ctx.external_hosts


def test_sitemap_and_crawl_sets_are_comparable(ctx):
    assert ctx.in_sitemap_not_crawled() == {"https://example.com/never-crawled"}
    assert "https://example.com/orphan" in ctx.crawled_not_in_sitemap()


def test_a_redirect_indexes_the_page_at_its_destination():
    c = build_context(FakeCrawl(site_url=S, pages=[
        FakePage(url="https://example.com/old", final_url="https://example.com/new",
                 parsed=FakeParsed([])),
    ]))
    assert "https://example.com/new" in c.crawled_urls
    # a link to either form still finds the page
    assert c.page("https://example.com/old") is not None
    assert c.page("https://example.com/new") is not None


def test_an_empty_crawl_does_not_explode():
    c = build_context(FakeCrawl(site_url=S))
    assert c.crawled_urls == set()
    assert c.orphans() == set()
    assert c.depth_of("https://example.com/") == UNREACHABLE


def test_a_page_with_no_parsed_body_is_still_a_node():
    c = build_context(FakeCrawl(site_url=S, pages=[FakePage(url=S, parsed=None)]))
    assert c.home in c.crawled_urls


def test_a_link_cycle_terminates():
    c = build_context(FakeCrawl(site_url=S, pages=[
        page("/", ["/a"]), page("/a", ["/b"]), page("/b", ["/a", "/"]),
    ]))
    assert c.depth_of("https://example.com/b") == 2
