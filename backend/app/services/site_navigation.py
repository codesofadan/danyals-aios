"""Assemble a client's navigation from its PUBLISHED content pages.

The bulk-content flow (`POST /content/research/generate`) fans a page set into
individual content jobs; each publishes its own WordPress page. Nothing then wired the
pages into a nested navbar — a "Services"/"Locations"/"Blog" parent whose dropdown lists
the bulk pages under it. This module is that missing last mile: it maps a client's
published jobs to `site_plan` page dicts (grouped by `page_type` so the family hub
nests them), and the caller hands the resulting plan to the AIOS Publisher plugin's
`/site` route, which upserts the pages and (re)builds the nested menu idempotently.

Pure + I/O-free on purpose: the router gathers the jobs and delivers the plan; this
layer only does the deterministic mapping, so it is unit-tested without a DB or a site.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


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
        pages.append(
            {
                "title": title,
                "slug": slug,
                "page_type": str(job.get("page_type") or "").strip().lower(),
                "in_menu": True,
            }
        )
    return pages
