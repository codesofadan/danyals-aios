"""Assemble a client's navigation from its PUBLISHED content pages.

The bulk-content flow (`POST /content/research/generate`) fans a page set into
individual content jobs; each publishes its own WordPress page. Nothing then wired the
pages into a nested navbar — a "Services"/"Locations"/"Blog" parent whose dropdown lists
the bulk pages under it. This module is that missing last mile: it maps a client's
published jobs to `site_plan` page dicts (grouped by `page_type` so the family hub
nests them), and the caller hands the resulting plan to the AIOS Publisher plugin's
`/site` route, which upserts the pages and (re)builds the nested menu idempotently.

THIS DELIVERY IS STRUCTURAL, AND THAT IS A SAFETY PROPERTY, NOT AN OMISSION.

It carries slugs, hierarchy, menu order and the identity of the post each page ALREADY
is. It deliberately carries NO body and NO SEO fields, because it knows neither: the
page's body and meta were written by the content pipeline and are live on the site, and
this module is looking at a job row, not at the page.

Saying that out loud matters because the first version said it by accident. It emitted
page dicts with no `content` key, `PlannedPage.content` defaulted to `""`, and the
plugin wrote `post_content` unconditionally — so rebuilding the navigation EMPTIED the
body of every page in it. The fix is on both sides (absent-vs-empty here, write-only-
what-was-sent in the plugin), and the invariant worth keeping is this one: a structural
delivery sends structure. If it ever needs to carry content, it has to read the page.

Pure + I/O-free on purpose: the router gathers the jobs and delivers the plan; this
layer only does the deterministic mapping, so it is unit-tested without a DB or a site.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.site_plan import post_type_for_page_type


def _slug_from_url(url: str) -> str:
    """The last path segment of a published page URL (its WordPress slug), or ''."""
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else ""


def navigation_pages_from_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map PUBLISHED content jobs to ``site_plan`` page dicts for nav assembly.

    Only jobs that actually PUBLISHED (carry a ``wp_url``) are included — an unpublished
    or failed job has no live page to put in the menu. ``page_type`` (service / local /
    blog) is carried through verbatim so :func:`app.services.site_plan.build_site_plan`
    groups each page under its family hub (auto-creating the hub when absent). Duplicate
    slugs are de-duplicated (the first published page wins) so the menu never doubles a
    link. Order is preserved from the caller (newest-first from the repo).

    ``wp_post_id`` is carried when the job recorded one, because it identifies the post
    EXACTLY. Slug matching cannot: a blog article publishes as a WordPress ``post``, and
    a lookup for a ``page`` of that slug finds nothing and creates an empty duplicate
    beside the real article. ``post_type`` is the fallback for a page published before
    the id was recorded — derived from ``page_type`` by the same rule the publish path
    used, so the two agree.

    NO ``content`` key and no SEO keys, deliberately — see the module docstring.
    """
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in jobs:
        url = str(job.get("wp_url") or "").strip()
        if not url:
            continue
        title = str(job.get("topic") or "").strip()
        slug = _slug_from_url(url) or title
        if not slug:
            continue
        key = slug.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        page_type = str(job.get("page_type") or "").strip().lower()
        page: dict[str, Any] = {
            "title": title,
            "slug": slug,
            "page_type": page_type,
            "post_type": post_type_for_page_type(page_type),
            "in_menu": True,
        }
        # Only when the job actually recorded one. A blank / unparseable id is no id,
        # and `build_site_plan` drops it rather than sending a 0 the plugin would have
        # to interpret.
        post_id = job.get("wp_post_id")
        if post_id not in (None, ""):
            page["post_id"] = post_id
        pages.append(page)
    return pages
