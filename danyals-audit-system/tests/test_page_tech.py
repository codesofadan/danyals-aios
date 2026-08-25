"""Per-page technical checks over data the parser already produced.

Schema blocks, Open Graph, Twitter cards, canonical tags and semantic
landmarks were all parsed and then discarded, because nothing read them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import page_tech as pt

U = "https://example.com/blog/a-good-slug"


@dataclass
class P:
    url: str = U
    canonical: str | None = U
    schema_blocks: list = field(default_factory=list)
    schema_errors: list = field(default_factory=list)
    opengraph: dict = field(default_factory=dict)
    twitter: dict = field(default_factory=dict)
    semantic_tag_counts: dict = field(default_factory=dict)
    has_breadcrumb_nav: bool = False
    has_amp: bool = False
    has_noindex: bool = False
    has_nofollow_meta: bool = False
    meta_robots: str | None = None


@dataclass
class CP:
    final_url: str = "https://example.com/"
    html: str | None = "<html><body></body></html>"


def og_full():
    return dict.fromkeys(pt.OG_REQUIRED, "v")


PAGE_CHECKS = [
    pt.check_canonical_tag, pt.check_structured_data, pt.check_schema_errors,
    pt.check_broken_structured_data, pt.check_rich_result_eligibility,
    pt.check_breadcrumb_schema, pt.check_open_graph, pt.check_twitter_card,
    pt.check_semantic_html, pt.check_amp, pt.check_crawlability_on_page, pt.check_slug,
]


@pytest.mark.parametrize("fn", PAGE_CHECKS, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for p in (P(), P(schema_blocks=[{"@type": "Article", "headline": "H"}], opengraph=og_full())):
        v = fn(p)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0
        if v.status == "n_a":
            assert not v.remediation


# --- canonical --------------------------------------------------------------

def test_a_self_referencing_canonical_passes():
    assert pt.check_canonical_tag(P()).status == "pass"


def test_a_trailing_slash_difference_is_still_self_referencing():
    """Normalisation (O-2) says these are one page, so this must not warn."""
    assert pt.check_canonical_tag(P(url=U, canonical=U + "/")).status == "pass"


def test_no_canonical_is_critical():
    v = pt.check_canonical_tag(P(canonical=None))
    assert v.status == "fail" and v.severity == "critical"


def test_a_relative_canonical_warns():
    assert pt.check_canonical_tag(P(canonical="/other")).status == "warn"


def test_a_canonical_pointing_elsewhere_warns():
    v = pt.check_canonical_tag(P(canonical="https://example.com/different"))
    assert v.status == "warn"
    assert "de-indexing" in v.remediation


# --- structured data --------------------------------------------------------

def test_no_schema_fails():
    assert pt.check_structured_data(P()).status == "fail"


def test_unparseable_schema_scores_worse_than_none():
    only_errors = pt.check_structured_data(P(schema_errors=["bad json"]))
    none_at_all = pt.check_structured_data(P())
    assert only_errors.score < none_at_all.score


def test_valid_schema_passes():
    v = pt.check_structured_data(P(schema_blocks=[{"@type": "Article", "headline": "H"}]))
    assert v.status == "pass"


def test_schema_errors_are_n_a_when_there_is_no_schema_at_all():
    assert pt.check_schema_errors(P()).status == "n_a"


def test_schema_errors_fail_when_present():
    assert pt.check_schema_errors(P(schema_errors=["x"])).status == "fail"


def test_schema_that_parses_but_misses_a_required_property_is_caught():
    """The quiet failure: valid JSON, no rich result, no obvious reason."""
    v = pt.check_broken_structured_data(P(schema_blocks=[{"@type": "Recipe", "name": "Cake"}]))
    assert v.status == "fail"
    assert v.evidence["incomplete"][0]["type"] == "Recipe"
    assert "recipeIngredient" in v.evidence["incomplete"][0]["missing"]


def test_a_complete_schema_block_passes():
    block = {"@type": "Event", "name": "N", "startDate": "2026-01-01", "location": "L"}
    assert pt.check_broken_structured_data(P(schema_blocks=[block])).status == "pass"


def test_a_type_with_no_documented_requirements_is_not_penalised():
    assert pt.check_broken_structured_data(P(schema_blocks=[{"@type": "WebSite"}])).status == "pass"


def test_a_list_valued_at_type_is_handled():
    block = {"@type": ["Article", "BlogPosting"], "headline": "H"}
    assert pt.check_broken_structured_data(P(schema_blocks=[block])).status == "pass"


def test_rich_result_eligibility_needs_a_renderable_type():
    assert pt.check_rich_result_eligibility(P(schema_blocks=[{"@type": "WebSite"}])).status == "warn"
    assert pt.check_rich_result_eligibility(P(schema_blocks=[{"@type": "Product"}])).status == "pass"


def test_breadcrumb_markup_present_without_schema_is_the_easy_half_missing():
    v = pt.check_breadcrumb_schema(P(has_breadcrumb_nav=True))
    assert v.status == "warn"
    assert "easy half" in v.remediation


def test_breadcrumb_schema_passes():
    assert pt.check_breadcrumb_schema(P(schema_blocks=[{"@type": "BreadcrumbList"}])).status == "pass"


# --- social -----------------------------------------------------------------

def test_open_graph_uses_the_four_properties_ogp_me_requires():
    assert pt.check_open_graph(P(opengraph=og_full())).status == "pass"
    v = pt.check_open_graph(P(opengraph={"og:title": "t"}))
    assert v.status == "fail"
    assert set(v.evidence["missing_required"]) == {"og:type", "og:image", "og:url"}
    assert v.evidence["required_by"] == "ogp.me"


def test_no_open_graph_at_all_fails():
    assert pt.check_open_graph(P()).status == "fail"


def test_twitter_falls_back_to_open_graph_when_present():
    v = pt.check_twitter_card(P(opengraph=og_full()))
    assert v.status == "warn"
    assert v.evidence["open_graph_fallback"] is True


def test_no_twitter_card_and_no_open_graph_is_worse():
    v = pt.check_twitter_card(P())
    assert v.status == "fail"


def test_a_complete_twitter_card_passes():
    tw = dict.fromkeys(pt.TWITTER_REQUIRED + pt.TWITTER_RECOMMENDED, "v")
    assert pt.check_twitter_card(P(twitter=tw)).status == "pass"


# --- structure --------------------------------------------------------------

def test_no_semantic_landmarks_fails():
    assert pt.check_semantic_html(P()).status == "fail"


def test_more_than_one_main_element_warns():
    v = pt.check_semantic_html(P(semantic_tag_counts={"main": 2, "header": 1}))
    assert v.status == "warn" and "Exactly one" in v.remediation


def test_three_landmarks_including_main_passes():
    v = pt.check_semantic_html(P(semantic_tag_counts={"main": 1, "header": 1, "footer": 1}))
    assert v.status == "pass"


def test_a_page_without_amp_is_not_deficient():
    """Google dropped the Top Stories AMP requirement in 2021."""
    v = pt.check_amp(P())
    assert v.status == "n_a"
    assert "2021" in v.evidence["reason"]


def test_an_amp_page_without_a_canonical_warns():
    assert pt.check_amp(P(has_amp=True, canonical=None)).status == "warn"


def test_meta_noindex_is_critical():
    v = pt.check_crawlability_on_page(P(has_noindex=True))
    assert v.status == "fail" and v.severity == "critical"


def test_meta_nofollow_is_a_major_warning():
    assert pt.check_crawlability_on_page(P(has_nofollow_meta=True)).status == "warn"


# --- slug -------------------------------------------------------------------

def test_a_clean_slug_passes():
    assert pt.check_slug(P()).status == "pass"


def test_the_homepage_has_no_slug_to_judge():
    assert pt.check_slug(P(url="https://example.com/")).status == "n_a"


@pytest.mark.parametrize("url,problem", [
    ("https://example.com/blog/my_post", "underscores"),
    ("https://example.com/blog/MyPost", "upper case"),
    ("https://example.com/blog/page.php", "file extension"),
    ("https://example.com/blog/12345", "numeric id"),
    ("https://example.com/a/b/c/d/e/f", "path levels"),
])
def test_slug_problems_are_named(url, problem):
    v = pt.check_slug(P(url=url))
    assert v.status == "warn"
    assert any(problem in p for p in v.evidence["problems"]), v.evidence["problems"]


def test_the_slug_threshold_is_labelled_a_convention():
    """Google calls URL words a very small ranking factor."""
    assert "convention" in pt.check_slug(P()).evidence["threshold_basis"]


# --- mixed content ----------------------------------------------------------

def test_mixed_content_is_n_a_on_an_http_page():
    v = pt.check_mixed_content(CP(final_url="http://example.com/"))
    assert v.status == "n_a"


def test_an_https_page_loading_http_resources_is_critical():
    html = '<img src="http://cdn.example.com/a.png"><script src="http://x.com/b.js"></script>'
    v = pt.check_mixed_content(CP(final_url="https://example.com/", html=html))
    assert v.status == "fail" and v.severity == "critical"
    assert v.evidence["http_resource_count"] == 2


def test_a_clean_https_page_passes():
    html = '<img src="https://cdn.example.com/a.png">'
    assert pt.check_mixed_content(CP(html=html)).status == "pass"


def test_mixed_content_is_n_a_without_a_body():
    assert pt.check_mixed_content(CP(html=None)).status == "n_a"
