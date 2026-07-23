"""Wave 5: unit tests for the deterministic content-layout heuristic."""

from __future__ import annotations

import pytest

from app.services.content_layout import LAYOUTS, pick_layout

pytestmark = pytest.mark.unit


def test_gbp_post_is_a_card() -> None:
    assert pick_layout("gbp_post").key == "gbp-card"


def test_local_page_is_a_landing() -> None:
    assert pick_layout("local").key == "local-landing"
    # has_local forces the local landing even for a non-local page_type.
    assert pick_layout("blog", has_local=True).key == "local-landing"


def test_service_page_is_a_hero() -> None:
    assert pick_layout("service").key == "service-hero"


def test_blog_long_form_with_faq() -> None:
    assert pick_layout("blog", words=1800, has_faq=True).key == "long-form-toc"
    # Long but NO faq -> not the TOC layout.
    assert pick_layout("blog", words=1800, has_faq=False).key == "standard-article"


def test_blog_media_rich() -> None:
    assert pick_layout("blog", images=4, words=800).key == "media-rich"


def test_blog_default_standard() -> None:
    assert pick_layout("blog", images=1, words=800, has_faq=False).key == "standard-article"
    # Unknown page types fall through to the blog rules.
    assert pick_layout("mystery").key == "standard-article"


def test_every_choice_is_a_known_layout_and_deterministic() -> None:
    cases = [
        ("gbp_post", {}),
        ("local", {}),
        ("service", {}),
        ("blog", {"words": 2000, "has_faq": True}),
        ("blog", {"images": 5}),
        ("blog", {}),
    ]
    for page_type, kw in cases:
        first = pick_layout(page_type, **kw)  # type: ignore[arg-type]
        second = pick_layout(page_type, **kw)  # type: ignore[arg-type]
        assert first == second  # deterministic
        assert first.key in LAYOUTS
        assert first.label == LAYOUTS[first.key]
        assert first.reason
