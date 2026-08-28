"""The last checks whose inputs were already free.

Ledgered as not_yet_built - the only reason that claims no blocker exists
beyond the work itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import media_content as mc
from audit_engine.analyzers.context import build_context

S = "https://example.com/"


@dataclass
class Img:
    src: str
    alt: str | None = "a description"


@dataclass
class L:
    href: str


@dataclass
class P:
    title: str | None = "Dental implants in Lahore"
    h1s: list = field(default_factory=lambda: ["Dental implants"])
    word_count: int = 800
    images: list = field(default_factory=list)
    links: list = field(default_factory=list)
    schema_blocks: list = field(default_factory=list)
    body_text: str = "word " * 800


@dataclass
class Page:
    url: str
    final_url: str | None = None
    http_status: int = 200
    parsed: P | None = None
    html: str | None = ""

    def __post_init__(self):
        if self.final_url is None:
            self.final_url = self.url
        if self.parsed is None:
            self.parsed = P()


@dataclass
class SM:
    url: str = "https://example.com/sitemap.xml"
    urls: list = field(default_factory=list)
    child_sitemaps: list = field(default_factory=list)
    status_code: int = 200
    error: str | None = None


@dataclass
class Robots:
    blocked_prefix: str | None = None

    def is_allowed(self, path, user_agent="*"):
        return not (self.blocked_prefix and path.startswith(self.blocked_prefix))


@dataclass
class Crawl:
    site_url: str = S
    pages: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    discovered_urls: list = field(default_factory=list)
    robots: object | None = None


def pg(path, **kw):
    parsed = kw.pop("parsed", None) or P()
    return Page(url=f"https://example.com{path}", parsed=parsed, **kw)


def ctx_of(**kw):
    return build_context(Crawl(**kw))


ALL = [mc.check_thin_pages, mc.check_internal_topical_relevance,
       mc.check_sitemap_xml_errors, mc.check_image_crawlability,
       mc.check_image_indexing, mc.check_video_indexing]


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_an_empty_crawl_is_n_a(fn):
    v = fn(ctx_of())
    assert v.status == "n_a" and not v.remediation


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for c in (ctx_of(), ctx_of(pages=[pg("/")], sitemaps=[SM()], robots=Robots())):
        v = fn(c)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0


# --- thin pages -------------------------------------------------------------

def test_a_few_short_pages_are_normal():
    """A contact page is meant to be brief. Flagging it is how an audit fills a
    report with work nobody should do."""
    pages = [pg(f"/p{i}") for i in range(9)] + [pg("/contact", parsed=P(word_count=40))]
    v = mc.check_thin_pages(ctx_of(pages=pages))
    assert v.status == "pass"
    assert "meant to be brief" in v.evidence["note"]


def test_a_site_that_is_mostly_thin_fails():
    pages = [pg(f"/p{i}", parsed=P(word_count=40)) for i in range(8)] + [pg("/good")]
    v = mc.check_thin_pages(ctx_of(pages=pages))
    assert v.status == "fail" and v.severity == "major"
    assert v.evidence["thin_pages"] == 8


def test_the_word_threshold_is_labelled_judgement():
    """Google publishes no word count."""
    v = mc.check_thin_pages(ctx_of(pages=[pg("/")]))
    assert "judgement" in v.evidence["threshold_basis"]


# --- topical relevance ------------------------------------------------------

def test_too_few_linked_pairs_is_n_a_not_a_verdict():
    c = ctx_of(pages=[pg("/", parsed=P(links=[L("/a")])), pg("/a")])
    v = mc.check_internal_topical_relevance(c)
    assert v.status == "n_a"
    assert "too few" in v.evidence["reason"]


def test_links_between_related_pages_pass():
    def same(hrefs):
        return P(title="Dental implants Lahore", h1s=["Dental implants"],
                 links=[L(h) for h in hrefs])

    pages = [pg(f"/p{i}", parsed=same([f"/p{j}" for j in range(6) if j != i]))
             for i in range(6)]
    v = mc.check_internal_topical_relevance(ctx_of(pages=pages))
    assert v.status == "pass"
    assert v.evidence["related_share"] == 1.0


def test_links_between_unrelated_pages_fail():
    topics = ["Dental implants", "Kitchen recipes", "Motorbike repair",
              "Tax advice", "Wedding venues", "Guitar lessons"]
    pages = [pg(f"/p{i}", parsed=P(title=topics[i], h1s=[topics[i]],
                                   links=[L(f"/p{j}") for j in range(6) if j != i]))
             for i in range(6)]
    v = mc.check_internal_topical_relevance(ctx_of(pages=pages))
    assert v.status == "fail"


def test_the_method_is_described_honestly():
    """A lexical overlap must not imply a semantic model."""
    c = ctx_of(pages=[pg("/")])
    assert "not a semantic model" in mc.check_internal_topical_relevance(c).evidence["method"]


# --- sitemap XML ------------------------------------------------------------

def test_no_sitemap_is_n_a():
    assert mc.check_sitemap_xml_errors(ctx_of(pages=[pg("/")])).status == "n_a"


def test_a_sitemap_that_fails_to_parse_is_a_failure():
    c = ctx_of(pages=[pg("/")], sitemaps=[SM(error="not well-formed: line 12")])
    v = mc.check_sitemap_xml_errors(c)
    assert v.status == "fail" and v.severity == "major"
    assert "drops every URL after it" in v.remediation


def test_an_empty_sitemap_warns():
    c = ctx_of(pages=[pg("/")], sitemaps=[SM()])
    assert mc.check_sitemap_xml_errors(c).status == "warn"


def test_a_healthy_sitemap_passes():
    c = ctx_of(pages=[pg("/")], sitemaps=[SM(urls=["https://example.com/"])])
    assert mc.check_sitemap_xml_errors(c).status == "pass"


# --- images -----------------------------------------------------------------

def test_no_robots_means_image_crawlability_cannot_be_judged():
    c = ctx_of(pages=[pg("/", parsed=P(images=[Img("/img/a.png")]))])
    v = mc.check_image_crawlability(c)
    assert v.status == "n_a"
    assert "robots.txt was not fetched" in v.evidence["reason"]


def test_images_blocked_by_robots_are_reported():
    c = ctx_of(pages=[pg("/", parsed=P(images=[Img("/private/a.png"), Img("/ok/b.png")]))],
               robots=Robots(blocked_prefix="/private"))
    v = mc.check_image_crawlability(c)
    assert v.status == "warn"
    assert v.evidence["blocked_by_robots"] == 1


def test_unblocked_images_pass():
    c = ctx_of(pages=[pg("/", parsed=P(images=[Img("/ok/a.png")]))], robots=Robots())
    assert mc.check_image_crawlability(c).status == "pass"


def test_a_page_with_no_images_is_n_a_for_crawlability():
    c = ctx_of(pages=[pg("/")], robots=Robots())
    assert mc.check_image_crawlability(c).status == "n_a"


def test_missing_alt_text_is_reported():
    imgs = [Img("/a.png", alt=None), Img("/b.png", alt=""), Img("/c.png")]
    v = mc.check_image_indexing(ctx_of(pages=[pg("/", parsed=P(images=imgs))]))
    assert v.status in {"warn", "fail"}
    assert v.evidence["without_alt"] == 2
    assert "only description Google has" in v.remediation


def test_images_with_alt_pass():
    c = ctx_of(pages=[pg("/", parsed=P(images=[Img("/a.png")]))])
    assert mc.check_image_indexing(c).status == "pass"


def test_no_images_is_n_a_for_indexing():
    assert mc.check_image_indexing(ctx_of(pages=[pg("/")])).status == "n_a"


# --- video ------------------------------------------------------------------

def test_a_site_with_no_video_is_not_failing_a_video_check():
    """Saying so would be noise on most sites."""
    v = mc.check_video_indexing(ctx_of(pages=[pg("/")]))
    assert v.status == "n_a"
    assert "nothing to index" in v.evidence["reason"]


@pytest.mark.parametrize("html", [
    '<video src="/a.mp4"></video>',
    '<iframe src="https://www.youtube.com/embed/abc"></iframe>',
    '<iframe src="https://player.vimeo.com/video/1"></iframe>',
])
def test_video_is_detected_in_several_forms(html):
    c = ctx_of(pages=[Page(url=S, html=html)])
    v = mc.check_video_indexing(c)
    assert v.evidence["pages_with_video"] == 1


def test_video_without_schema_warns():
    c = ctx_of(pages=[Page(url=S, html='<video src="/a.mp4"></video>')])
    v = mc.check_video_indexing(c)
    assert v.status == "warn"
    assert "VideoObject" in v.remediation


def test_video_with_schema_passes():
    p = P(schema_blocks=[{"@type": "VideoObject", "name": "n"}])
    c = ctx_of(pages=[Page(url=S, html='<video src="/a.mp4"></video>', parsed=p)])
    assert mc.check_video_indexing(c).status == "pass"


def test_a_list_valued_schema_type_is_handled():
    p = P(schema_blocks=[{"@type": ["VideoObject", "Clip"]}])
    c = ctx_of(pages=[Page(url=S, html='<video src="/a.mp4"></video>', parsed=p)])
    assert mc.check_video_indexing(c).status == "pass"


def test_not_yet_built_now_means_only_what_we_cannot_fetch():
    """The claim this reason makes, finally true of everything under it.

    Its docstring always said "needs an input we do not fetch", but three of the
    five sat there needing nothing of the sort: ON-070, TECH-082 and TECH-090 read
    the crawled HTML and response headers this audit already collects, and were
    simply unwritten. They are built.

    The two left genuinely need a SECOND fetch of the same page - one under a
    mobile viewport against a desktop one (ON-083), one under Googlebot's
    user-agent against a browser's (TECH-084). That doubles crawl cost per page,
    which is a decision about what an audit spends, not a gap in the analyzers.
    """
    from audit_engine.analyzers.ledger import LEDGER, Reason

    remaining = {c for c, e in LEDGER.items() if e.reason is Reason.NOT_YET_BUILT}
    assert remaining == {"ON-083", "TECH-084"}
