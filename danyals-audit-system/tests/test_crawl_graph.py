"""Site-wide checks over the crawl graph.

These were impossible to write correctly before Wave 1, because each analyzer
derived its own link graph with its own URL handling and they disagreed about
what counted as the same page.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import crawl_graph as g
from audit_engine.analyzers.context import build_context

S = "https://example.com/"


@dataclass
class L:
    href: str


@dataclass
class Hop:
    url: str
    status: int = 301
    location: str | None = None


@dataclass
class P:
    title: str | None = "T"
    h1s: list = field(default_factory=list)
    body_text: str = "word " * 300
    word_count: int = 300
    has_noindex: bool = False
    links: list = field(default_factory=list)


@dataclass
class Page:
    url: str
    final_url: str | None = None
    http_status: int = 200
    parsed: P | None = None
    redirect_hops: list = field(default_factory=list)

    def __post_init__(self):
        if self.final_url is None:
            self.final_url = self.url
        if self.parsed is None:
            self.parsed = P()


@dataclass
class SM:
    urls: list = field(default_factory=list)


@dataclass
class Robots:
    allowed: bool = True

    def is_allowed(self, path, user_agent="*"):
        return self.allowed


@dataclass
class Crawl:
    site_url: str = S
    pages: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    discovered_urls: list = field(default_factory=list)
    robots: object | None = None


def pg(path, links=(), **kw):
    # Distinct body per page: identical copy would (correctly) trip the
    # duplicate-page check and make "healthy site" fixtures dishonest.
    p = P(links=[L(h) for h in links], body_text=f"{path} unique copy " * 60)
    return Page(url=f"https://example.com{path}", parsed=p, **kw)


def ctx_of(**kw):
    return build_context(Crawl(**kw))


ALL = [
    g.check_404_errors, g.check_5xx_errors, g.check_soft_404,
    g.check_redirect_loops, g.check_301_chains, g.check_302_misuse,
    g.check_orphan_urls, g.check_crawl_traps, g.check_duplicate_urls,
    g.check_duplicate_pages, g.check_url_parameter_indexing,
    g.check_faceted_navigation, g.check_search_page_indexing,
    g.check_www_consistency, g.check_trailing_slash_consistency,
    g.check_internal_linking_crawl, g.check_link_equity_flow,
    g.check_sitemap_url_status, g.check_sitemap_indexability, g.check_hidden_pages,
]


# --- contracts every check must honour --------------------------------------

@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_an_empty_crawl_is_n_a_not_a_failure(fn):
    v = fn(ctx_of())
    assert v.status == "n_a", f"{fn.__name__} scored a crawl with no pages"
    assert not v.remediation


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_a_healthy_site_passes(fn):
    c = ctx_of(
        pages=[pg("/", ["/a", "/b"]), pg("/a", ["/b"]), pg("/b", ["/a"])],
        sitemaps=[SM(["https://example.com/", "https://example.com/a", "https://example.com/b"])],
        robots=Robots(),
    )
    v = fn(c)
    assert v.status in {"pass", "n_a"}, f"{fn.__name__} flagged a clean site: {v.evidence}"


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for c in (ctx_of(), ctx_of(pages=[pg("/", ["/a"]), pg("/a")])):
        v = fn(c)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0
        assert isinstance(v.evidence, dict)


# --- broken pages -----------------------------------------------------------

def test_a_linked_404_is_critical():
    c = ctx_of(pages=[pg("/", ["/gone"]), pg("/gone", http_status=404)])
    v = g.check_404_errors(c)
    assert v.status == "fail" and v.severity == "critical"
    assert v.evidence["linked_not_found_count"] == 1


def test_an_unlinked_404_is_only_a_warning():
    """Nothing links to it, so it strands nobody."""
    c = ctx_of(pages=[pg("/"), pg("/gone", http_status=404)])
    v = g.check_404_errors(c)
    assert v.status == "warn"


def test_a_5xx_is_critical_and_scores_zero():
    c = ctx_of(pages=[pg("/"), pg("/boom", http_status=503)])
    v = g.check_5xx_errors(c)
    assert v.status == "fail" and v.score == 0.0


def test_a_soft_404_returns_200_while_saying_not_found():
    p = P(title="Page Not Found", body_text="x", word_count=3)
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/x", parsed=p)])
    v = g.check_soft_404(c)
    assert v.status == "fail"
    assert v.evidence["soft_404_count"] == 1


# --- redirects --------------------------------------------------------------

def test_a_redirect_loop_is_critical():
    hops = [Hop("https://example.com/a"), Hop("https://example.com/b"), Hop("https://example.com/a")]
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", redirect_hops=hops)])
    v = g.check_redirect_loops(c)
    assert v.status == "fail" and v.severity == "critical"


def test_a_two_hop_chain_warns_and_a_long_chain_fails():
    two = [Hop("https://example.com/1"), Hop("https://example.com/2")]
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", redirect_hops=two)])
    assert g.check_301_chains(c).status == "warn"

    four = [Hop(f"https://example.com/{i}") for i in range(4)]
    c2 = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", redirect_hops=four)])
    assert g.check_301_chains(c2).status == "fail"


def test_the_redirect_hop_threshold_is_labelled_a_convention():
    """Google publishes no hop limit; the widely-quoted figure is lore."""
    two = [Hop("https://example.com/1"), Hop("https://example.com/2")]
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", redirect_hops=two)])
    assert "convention" in g.check_301_chains(c).evidence["threshold_basis"]


@pytest.mark.parametrize("status", [302, 303, 307])
def test_a_temporary_redirect_is_flagged(status):
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a",
                                    redirect_hops=[Hop("https://example.com/b", status)])])
    v = g.check_302_misuse(c)
    assert v.status == "warn" and v.severity == "major"


def test_a_301_is_not_flagged_as_temporary():
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a",
                                    redirect_hops=[Hop("https://example.com/b", 301)])])
    assert g.check_302_misuse(c).status == "pass"


# --- reachability -----------------------------------------------------------

def test_an_orphan_is_reported_and_the_homepage_is_not_one():
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a"), pg("/lonely")])
    v = g.check_orphan_urls(c)
    assert v.evidence["orphan_count"] == 1
    assert "https://example.com/lonely" in v.evidence["examples"]


def test_a_repeating_path_segment_is_a_crawl_trap():
    c = ctx_of(pages=[pg("/")],
               discovered_urls=["https://example.com/a/b/a/b/a/"])
    v = g.check_crawl_traps(c)
    assert v.status == "fail" and v.severity == "critical"


def test_many_parameter_variants_of_one_path_is_a_trap():
    urls = [f"https://example.com/list?p={i}" for i in range(30)]
    c = ctx_of(pages=[pg("/")], discovered_urls=urls)
    assert g.check_crawl_traps(c).status == "warn"


# --- duplication ------------------------------------------------------------

def test_two_urls_for_one_page_are_reported():
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a"),
                      Page(url="https://example.com/a/")])
    v = g.check_duplicate_urls(c)
    assert v.status == "warn" and v.evidence["duplicate_groups"] == 1


def test_identical_body_copy_across_urls_is_a_failure():
    same = P(body_text="the same words " * 60, word_count=180)
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", parsed=same),
                      Page(url="https://example.com/b", parsed=same)])
    v = g.check_duplicate_pages(c)
    assert v.status == "fail" and v.evidence["pages_in_a_duplicate_group"] == 2


def test_short_pages_are_excluded_from_duplicate_comparison():
    """Two near-empty pages are not evidence of duplication."""
    tiny = P(body_text="hi", word_count=1)
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a", parsed=tiny),
                      Page(url="https://example.com/b", parsed=tiny)])
    assert g.check_duplicate_pages(c).status == "pass"


# --- URL hygiene ------------------------------------------------------------

def test_a_tracking_parameter_url_is_flagged_as_a_duplicate_entry_point():
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a?utm_source=fb")])
    assert g.check_url_parameter_indexing(c).status == "warn"


def test_facet_parameters_are_detected():
    urls = [f"https://example.com/shop?color=red&sort=price&p={i}" for i in range(30)]
    c = ctx_of(pages=[pg("/")], discovered_urls=urls)
    v = g.check_faceted_navigation(c)
    assert v.status == "fail"
    assert "color" in v.evidence["parameters"]


def test_an_indexable_internal_search_page_fails():
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/?s=dentist")],
               discovered_urls=["https://example.com/?s=dentist"])
    assert g.check_search_page_indexing(c).status == "fail"


def test_a_noindexed_search_page_passes():
    noindex = P(has_noindex=True)
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/search/", parsed=noindex)],
               discovered_urls=["https://example.com/search/"])
    assert g.check_search_page_indexing(c).status == "pass"


# --- domain form ------------------------------------------------------------

def test_serving_both_www_and_bare_is_flagged():
    c = ctx_of(pages=[Page(url="https://example.com/"),
                      Page(url="https://www.example.com/a")])
    v = g.check_www_consistency(c)
    assert v.status == "warn"
    assert set(v.evidence["variants"]) == {"www", "bare"}


def test_mixed_trailing_slash_forms_are_flagged():
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/a/"),
                      Page(url="https://example.com/b")])
    assert g.check_trailing_slash_consistency(c).status == "warn"


# --- internal linking -------------------------------------------------------

def test_depth_distribution_is_reported():
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a", ["/b"]), pg("/b")])
    v = g.check_internal_linking_crawl(c)
    assert v.evidence["depth_distribution"] == {"0": 1, "1": 1, "2": 1}
    assert v.evidence["max_depth"] == 2


def test_pages_deeper_than_three_clicks_are_flagged():
    pages = [pg("/", ["/1"])] + [pg(f"/{i}", [f"/{i + 1}"]) for i in range(1, 6)] + [pg("/6")]
    v = g.check_internal_linking_crawl(ctx_of(pages=pages))
    assert v.status in {"warn", "fail"}
    assert v.evidence["deeper_than_3_clicks"] >= 1


def test_a_site_with_no_internal_links_fails_equity_flow():
    c = ctx_of(pages=[pg("/"), pg("/a"), pg("/b")])
    v = g.check_link_equity_flow(c)
    assert v.status == "fail"
    assert v.evidence["internal_links"] == 0


# --- sitemap ----------------------------------------------------------------

def test_a_sitemap_url_that_404s_is_a_failure():
    c = ctx_of(pages=[pg("/"), pg("/gone", http_status=404)],
               sitemaps=[SM(["https://example.com/", "https://example.com/gone"])])
    v = g.check_sitemap_url_status(c)
    assert v.status == "fail" and v.evidence["non_200"] == 1


def test_no_sitemap_is_n_a_not_a_failure():
    assert g.check_sitemap_url_status(ctx_of(pages=[pg("/")])).status == "n_a"


def test_a_noindex_url_listed_in_the_sitemap_is_a_contradiction():
    noindex = P(has_noindex=True)
    c = ctx_of(pages=[pg("/"), Page(url="https://example.com/x", parsed=noindex)],
               sitemaps=[SM(["https://example.com/x"])], robots=Robots())
    v = g.check_sitemap_indexability(c)
    assert v.status == "fail" and v.evidence["noindex_in_sitemap"] == 1


def test_a_robots_blocked_url_in_the_sitemap_is_flagged():
    c = ctx_of(pages=[pg("/"), pg("/x")],
               sitemaps=[SM(["https://example.com/x"])], robots=Robots(allowed=False))
    v = g.check_sitemap_indexability(c)
    assert v.status == "fail" and v.evidence["robots_blocked_in_sitemap"] >= 1


def test_a_page_with_no_link_and_no_sitemap_entry_is_hidden():
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a"), pg("/secret")],
               sitemaps=[SM(["https://example.com/", "https://example.com/a"])])
    v = g.check_hidden_pages(c)
    assert v.status == "warn"
    assert v.evidence["examples"] == ["https://example.com/secret"]


# --------------------------------------------------------------------------
# Partial crawls. A page cap is OUR limit, not the client's defect.
# --------------------------------------------------------------------------

def _partial():
    """8 pages crawled out of a 108-URL sitemap - the real smileon.pk shape."""
    return ctx_of(
        pages=[pg("/", ["/a"]), pg("/a")] + [pg(f"/p{i}") for i in range(6)],
        sitemaps=[SM([f"https://example.com/s{i}" for i in range(108)])],
    )


def test_a_partial_crawl_is_detected():
    c = _partial()
    assert c.is_partial is True
    assert c.coverage < 0.2


def test_a_complete_crawl_is_not_flagged_as_partial():
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a")],
               sitemaps=[SM(["https://example.com/", "https://example.com/a"])])
    assert c.is_partial is False
    assert c.coverage == 1.0


def test_click_depth_is_not_measured_on_a_partial_crawl():
    """Reporting "6 of 8 pages unreachable" when we simply did not fetch the
    linking pages measures our page cap, not their site."""
    v = g.check_internal_linking_crawl(_partial())
    assert v.status == "n_a"
    assert v.confidence == 0.0
    assert "complete crawl" in v.evidence["reason"]


def test_orphans_are_not_reported_on_a_partial_crawl():
    v = g.check_orphan_urls(_partial())
    assert v.status == "n_a"
    assert v.evidence["crawl_was_partial"] is True


def test_hidden_pages_are_not_reported_on_a_partial_crawl():
    assert g.check_hidden_pages(_partial()).status == "n_a"


def test_a_complete_crawl_still_reports_real_orphans():
    """The guard must not suppress the finding when the crawl IS complete."""
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a"), pg("/lonely")],
               sitemaps=[SM(["https://example.com/", "https://example.com/a",
                             "https://example.com/lonely"])])
    assert c.is_partial is False
    v = g.check_orphan_urls(c)
    assert v.status in {"warn", "fail"}
    assert v.evidence["orphan_count"] == 1


def test_a_complete_crawl_still_reports_real_depth():
    c = ctx_of(pages=[pg("/", ["/a"]), pg("/a", ["/b"]), pg("/b")],
               sitemaps=[SM(["https://example.com/", "https://example.com/a",
                             "https://example.com/b"])])
    v = g.check_internal_linking_crawl(c)
    assert v.status == "pass"
    assert v.evidence["max_depth"] == 2
