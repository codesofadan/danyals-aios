"""The navigation rebuild must not be able to erase a client's live pages.

THE DEFECT, in one sentence: ``navigation_pages_from_jobs`` emitted page dicts with no
``content`` key, ``PlannedPage.content`` defaulted to ``""``, and the plugin wrote
``post_content`` unconditionally - so rebuilding a client's navbar BLANKED the body of
every page in the menu. It was latent rather than live (no frontend surface called the
endpoint yet), and one button away from destroying fifty published pages.

The fix has two halves, on purpose, because the plugin and the platform ship
independently: the platform never SENDS a body it does not have, and the plugin never
WRITES one it was not sent. This file pins the platform half. The plugin half is pinned
by ``test_site_assembler_contract.py``, which reads the PHP.

A SECOND defect lived in the same delivery: every page was looked up as a WordPress
``page``, so a blog article - which publishes as a ``post`` - was never found, an empty
duplicate was created at its slug, and the menu pointed at the duplicate. The plan now
carries the post's identity.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.site_navigation import navigation_pages_from_jobs
from app.services.site_plan import (
    ARTICLE_PAGE_TYPES,
    PlannedPage,
    build_site_plan,
    post_type_for_page_type,
)

pytestmark = pytest.mark.unit


def _job(
    topic: str, page_type: str, wp_url: str, *, wp_post_id: Any = None
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "topic": topic, "page_type": page_type, "wp_url": wp_url, "status": "done",
    }
    if wp_post_id is not None:
        row["wp_post_id"] = wp_post_id
    return row


# --------------------------------------------------------------------------- #
# 1. Absent content is absent, not empty.
# --------------------------------------------------------------------------- #
def test_a_page_with_no_body_omits_the_content_key_entirely() -> None:
    """THE defect. `"content": ""` in the payload is an instruction to blank the live
    page; the absence of the key is an instruction to leave it alone. Re-inject by
    defaulting `PlannedPage.content` to `""` and this fails."""
    page = PlannedPage(slug="drain-cleaning", title="Drain Cleaning")
    assert page.content is None
    assert "content" not in page.payload()


def test_an_explicitly_empty_body_is_still_sent() -> None:
    """A caller must still be able to say "this page has no body" - which is why the
    field is nullable rather than just skipped when falsy."""
    page = PlannedPage(slug="x", title="X", content="")
    assert page.payload()["content"] == ""


def test_the_nav_rebuild_sends_no_body_for_any_page() -> None:
    """The whole navigation delivery, end to end: it knows slugs and hierarchy and
    nothing about page bodies, so not one page in it may carry a body."""
    jobs = [
        _job("Drain Cleaning", "service", "https://s.example/drain-cleaning/", wp_post_id=41),
        _job("Miami", "local", "https://s.example/miami/", wp_post_id=42),
        _job("Winter Tips", "blog", "https://s.example/winter-tips/", wp_post_id=43),
    ]
    plan = build_site_plan(navigation_pages_from_jobs(jobs), menu_location="primary")
    assert plan.valid
    published = {p["slug"] for p in plan.payload()["pages"] if "content" in p}
    # The auto-created hubs are the ONLY pages carrying a body, and only as a seed.
    assert published <= {"services", "locations", "blog"}
    for page in plan.payload()["pages"]:
        if page["slug"] in {"drain-cleaning", "miami", "winter-tips"}:
            assert "content" not in page, f"{page['slug']} would have its body overwritten"


def test_the_nav_rebuild_sends_no_seo_fields_either() -> None:
    """Same reasoning as the body: the meta is live on the site and this delivery did
    not read it, so sending a blank would erase a good SEO title."""
    plan = build_site_plan(
        navigation_pages_from_jobs([_job("A", "service", "https://s.example/a/", wp_post_id=9)])
    )
    page = next(p for p in plan.payload()["pages"] if p["slug"] == "a")
    for key in ("meta_title", "meta_description", "focus_keyword", "schema_jsonld",
                "og_title", "og_description", "og_image_url", "twitter_card",
                "design_css", "featured_image_url"):
        assert key not in page, f"{key} sent as a blank would erase the live value"


# --------------------------------------------------------------------------- #
# 2. The auto-created hub's placeholder is a SEED, not an authority.
# --------------------------------------------------------------------------- #
def test_an_auto_created_hub_marks_its_placeholder_as_seed_only() -> None:
    """The hub's "Explore our services." line must be written when the hub is created
    and NEVER again - otherwise every later nav rebuild replaces whatever real landing
    copy the operator wrote on it with that one line. Same class of bug as the body
    blanking, one level down."""
    plan = build_site_plan(
        navigation_pages_from_jobs([_job("A", "service", "https://s.example/a/")])
    )
    hub = next(p for p in plan.payload()["pages"] if p["slug"] == "services")
    assert hub["content"].startswith("<p>Explore our")
    assert hub["content_only_if_new"] is True


def test_a_real_page_is_not_flagged_seed_only() -> None:
    """The flag must be narrow: a genuine content delivery's body IS authoritative."""
    plan = build_site_plan([{"slug": "home", "title": "Home", "content": "<p>Real.</p>"}])
    page = plan.payload()["pages"][0]
    assert page["content"] == "<p>Real.</p>"
    assert "content_only_if_new" not in page


# --------------------------------------------------------------------------- #
# 3. The post's identity: id first, then the right post type.
# --------------------------------------------------------------------------- #
def test_the_published_post_id_travels_with_the_page() -> None:
    """An id cannot be wrong about which post it means, so it removes the whole class
    of slug/post-type mismatch the duplicate-page bug came from."""
    pages = navigation_pages_from_jobs(
        [_job("Winter Tips", "blog", "https://s.example/winter-tips/", wp_post_id=4471)]
    )
    assert pages[0]["post_id"] == 4471
    plan = build_site_plan(pages)
    assert next(p for p in plan.payload()["pages"] if p["slug"] == "winter-tips")["post_id"] == 4471


def test_a_blog_article_is_declared_a_post_not_a_page() -> None:
    """THE duplicate-page defect. A blog article publishes as a WordPress `post`; the
    assembler looked every page up as a `page`, found nothing, and created an empty
    duplicate that the menu then linked to instead of the article."""
    pages = navigation_pages_from_jobs(
        [_job("Winter Tips", "blog", "https://s.example/winter-tips/")]
    )
    assert pages[0]["post_type"] == "post"


def test_a_landing_page_is_declared_a_page() -> None:
    pages = navigation_pages_from_jobs(
        [_job("Drain Cleaning", "service", "https://s.example/drain-cleaning/")]
    )
    assert pages[0]["post_type"] == "page"


def test_the_article_page_type_set_is_shared_with_the_publish_path() -> None:
    """One definition. The publish path decides `post` vs `page` from this same set -
    a second copy is precisely how the site route came to disagree with it."""
    from workers.tasks.content import _ARTICLE_PAGE_TYPES

    assert _ARTICLE_PAGE_TYPES is ARTICLE_PAGE_TYPES
    assert post_type_for_page_type("blog") == "post"
    assert post_type_for_page_type("faq") == "post"
    assert post_type_for_page_type("service") == "page"
    assert post_type_for_page_type("") == "page"


def test_a_blank_or_zero_post_id_is_dropped_rather_than_sent() -> None:
    """A 0 would be an id the plugin has to interpret; absence is unambiguous."""
    for bad in (0, "", "not-a-number", None):
        pages = navigation_pages_from_jobs(
            [_job("A", "service", "https://s.example/a/", wp_post_id=bad)]
        )
        plan = build_site_plan(pages)
        page = next(p for p in plan.payload()["pages"] if p["slug"] == "a")
        assert "post_id" not in page, f"{bad!r} became a post_id"


# --------------------------------------------------------------------------- #
# 4. Re-parenting must not drop fields (the latent field-list bug).
# --------------------------------------------------------------------------- #
def test_a_page_nested_under_a_hub_keeps_every_field() -> None:
    """`build_site_plan` re-creates a page when it assigns a parent. That used to name
    8 fields explicitly, so a re-parented page silently lost every field added later -
    its post_id and its whole SEO block - while its unnested sibling kept them."""
    plan = build_site_plan([
        {
            "slug": "drain-cleaning", "title": "Drain Cleaning", "page_type": "service",
            "post_id": 41, "post_type": "post", "meta_title": "Drain Cleaning | Acme",
            "meta_description": "Fast drain cleaning.", "focus_keyword": "drain cleaning",
            "schema_jsonld": '{"@type":"Service"}', "design_css": ".x{}",
            "og_title": "OG", "og_description": "OGD", "og_image_url": "https://i/x.png",
            "twitter_card": "summary_large_image", "featured_image_url": "https://i/f.png",
            "full_width": True, "content": "<p>Body.</p>",
        }
    ])
    page = next(p for p in plan.pages if p.slug == "drain-cleaning")
    assert page.parent_slug == "services", "precondition: it WAS re-parented"
    assert page.post_id == 41
    assert page.post_type == "post"
    assert page.meta_title == "Drain Cleaning | Acme"
    assert page.meta_description == "Fast drain cleaning."
    assert page.focus_keyword == "drain cleaning"
    assert page.schema_jsonld == '{"@type":"Service"}'
    assert page.og_title == "OG" and page.og_description == "OGD"
    assert page.og_image_url == "https://i/x.png"
    assert page.twitter_card == "summary_large_image"
    assert page.design_css == ".x{}"
    assert page.featured_image_url == "https://i/f.png"
    assert page.full_width is True
    assert page.content == "<p>Body.</p>"


# --------------------------------------------------------------------------- #
# 5. A content delivery DOES carry its meta (the /site route's missing half).
# --------------------------------------------------------------------------- #
def test_a_content_delivery_carries_the_full_seo_block() -> None:
    """Before this, a page delivered as part of a SITE arrived with no SEO title, no
    description, no focus keyword and no schema - while the identical page pushed one
    at a time through `/publish` got all four."""
    plan = build_site_plan([{
        "slug": "home", "title": "Home", "content": "<p>Hi.</p>",
        "meta_title": "Acme Plumbing | Austin",
        "meta_description": "Emergency plumbing in Austin.",
        "focus_keyword": "austin plumber",
        "schema_jsonld": '{"@type":"LocalBusiness"}',
        "og_title": "Acme Plumbing", "og_description": "Emergency plumbing.",
        "og_image_url": "https://cdn.example/hero.jpg",
        "twitter_card": "summary_large_image",
        "design_css": ".aios-hero{color:red}",
        "featured_image_url": "https://cdn.example/hero.jpg",
        "full_width": True,
    }])
    page = plan.payload()["pages"][0]
    assert page["meta_title"] == "Acme Plumbing | Austin"
    assert page["meta_description"] == "Emergency plumbing in Austin."
    assert page["focus_keyword"] == "austin plumber"
    assert page["schema_jsonld"] == '{"@type":"LocalBusiness"}'
    assert page["og_title"] == "Acme Plumbing"
    assert page["og_image_url"] == "https://cdn.example/hero.jpg"
    assert page["twitter_card"] == "summary_large_image"
    assert page["design_css"] == ".aios-hero{color:red}"
    assert page["featured_image_url"] == "https://cdn.example/hero.jpg"
    assert page["full_width"] is True
