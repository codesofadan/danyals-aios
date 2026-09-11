"""Navigation assembly: a client's PUBLISHED content pages -> a nested navbar.

Proves the last-mile wiring end to end (minus the vault + HTTP): published jobs map to
site_plan page dicts, build_site_plan nests them under auto-created family hubs, and the
plan delivers through the plugin publisher seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.site_navigation import navigation_pages_from_jobs
from app.services.site_plan import build_site_plan
from integrations.wordpress_publisher import FakeWordPressPluginPublisher

pytestmark = pytest.mark.unit


def _job(topic: str, page_type: str, wp_url: str, status: str = "done") -> dict[str, Any]:
    return {"topic": topic, "page_type": page_type, "wp_url": wp_url, "status": status}


def test_only_published_pages_enter_the_nav() -> None:
    pages = navigation_pages_from_jobs([
        _job("Drain Cleaning", "service", "https://s.example/drain-cleaning/"),
        _job("Not published yet", "service", ""),  # no wp_url -> not in the menu
    ])
    assert [p["slug"] for p in pages] == ["drain-cleaning"]
    assert pages[0]["page_type"] == "service"


def test_slug_comes_from_the_published_url() -> None:
    pages = navigation_pages_from_jobs([_job("Any Title", "blog", "https://s.example/blog/winter-tips/")])
    assert pages[0]["slug"] == "winter-tips"


def test_duplicate_published_slugs_are_deduped() -> None:
    pages = navigation_pages_from_jobs([
        _job("A", "service", "https://s.example/x/"),
        _job("B", "service", "https://s.example/x/"),
    ])
    assert len(pages) == 1


def test_end_to_end_assembly_nests_bulk_pages_and_delivers() -> None:
    jobs = [
        _job("Drain Cleaning", "service", "https://s.example/drain-cleaning/"),
        _job("Slab Leak Repair", "service", "https://s.example/slab-leak-repair/"),
        _job("Miami", "local", "https://s.example/miami/"),
        _job("Winter Plumbing Tips", "blog", "https://s.example/winter-plumbing-tips/"),
    ]
    plan = build_site_plan(
        navigation_pages_from_jobs(jobs), menu_name="Acme Menu", menu_location="primary"
    )
    assert plan.valid
    parents = {p.slug: p.parent_slug for p in plan.pages}
    # bulk pages nest under their family hub...
    assert parents["drain-cleaning"] == "services"
    assert parents["slab-leak-repair"] == "services"
    assert parents["miami"] == "locations"
    assert parents["winter-plumbing-tips"] == "blog"
    # ...and the hubs were auto-created, sitting top-level as the dropdown parents.
    assert parents.get("services") == ""
    assert parents.get("locations") == ""
    assert parents.get("blog") == ""

    publisher = FakeWordPressPluginPublisher(site_url="https://s.example")
    result = publisher.deliver_site(plan.payload())
    assert isinstance(result, dict)
    assert len(publisher.delivered) == 1
    delivered = {p["slug"] for p in publisher.delivered[0]["pages"]}
    assert {"services", "drain-cleaning", "slab-leak-repair", "locations", "miami",
            "blog", "winter-plumbing-tips"} <= delivered
