"""A whole site as one order, not fifty unrelated pages (P6.5).

WHAT WAS ACTUALLY MISSING. The publish path sends ONE `PostDraft` at a time, and
nothing anywhere - not the plugin, not `site_builder`, not the content worker - creates
a navigation menu, assigns a homepage, or sets a page's parent. Verified by grep across
both sides: `wp_create_nav_menu`, `page_on_front`, `post_parent` and `menu_order` appear
nowhere. `homepage` exists only as a page_type LABEL.

So a fifty-page build produced fifty unlinked drafts. Every page was individually
correct and individually Elementor-editable, and the client still had to build the menu
by hand, pick a front page by hand, and nest the service pages by hand. "A few clicks to
a full website" fails at the last step, which is the step that makes it a website.

This module turns a set of produced pages into ONE ordered site plan: hierarchy, menu,
and front page, resolved and validated here so the plugin receives an instruction it can
apply idempotently rather than a pile of pages to guess at.

THREE THINGS IT REFUSES TO DO, because it writes to a live site:

  - it never deletes. A page the client wrote is not ours to remove, and a plan that
    can delete is a plan that can lose a client's work on a bad slug.
  - it never silently takes over the front page. Changing `show_on_front` changes what
    every visitor sees, so it happens only when explicitly asked for.
  - it never claims a menu location that already holds a menu unless told to. The
    client's existing navigation is theirs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# WordPress collapses a slug to lowercase alphanumerics and hyphens. Doing it here means
# the slug we use as an IDENTITY key is the same one WordPress will store - otherwise
# "Slab Leak Repair" is created once and then never matched again on re-run, and every
# republish makes a duplicate.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

MAX_MENU_DEPTH = 2


def slugify(value: str) -> str:
    """The slug WordPress will actually store for this title."""
    return _SLUG_STRIP.sub("-", (value or "").strip().lower()).strip("-")


@dataclass(frozen=True)
class PlannedPage:
    """One page in the site, with where it sits and whether it is navigable."""

    slug: str
    title: str
    content: str = ""
    elementor_data: str = ""
    template: str = ""
    parent_slug: str = ""
    menu_order: int = 0
    in_menu: bool = True
    is_front_page: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "title": self.title, "content": self.content,
            "elementor_data": self.elementor_data, "template": self.template,
            "parent_slug": self.parent_slug, "menu_order": self.menu_order,
            "in_menu": self.in_menu,
        }


@dataclass(frozen=True)
class SitePlan:
    """The whole order. `issues` is non-empty when it must not be sent."""

    pages: tuple[PlannedPage, ...] = ()
    menu_name: str = ""
    menu_location: str = ""
    front_page_slug: str = ""
    status: str = "draft"
    replace_existing_menu: bool = False
    issues: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def payload(self) -> dict[str, Any]:
        """What the plugin's /site endpoint receives."""
        return {
            "status": self.status,
            "pages": [p.payload() for p in self.pages],
            "menu": {
                "name": self.menu_name,
                "location": self.menu_location,
                "replace_existing": self.replace_existing_menu,
            },
            # Empty string means "do not touch the front page". Absent would be
            # ambiguous; empty is a decision.
            "front_page_slug": self.front_page_slug,
        }


def build_site_plan(
    pages: list[dict[str, Any]],
    *,
    menu_name: str = "Main Menu",
    menu_location: str = "",
    front_page_slug: str = "",
    status: str = "draft",
    replace_existing_menu: bool = False,
) -> SitePlan:
    """Resolve produced pages into one validated site plan.

    Total: never raises. Every problem is an `issue`, because a half-valid plan sent to
    a live site is worse than a refusal an operator can read.
    """
    planned: list[PlannedPage] = []
    issues: list[str] = []
    notes: list[str] = []
    seen: dict[str, int] = {}

    for index, raw in enumerate(pages):
        title = str(raw.get("title") or "").strip()
        slug = slugify(str(raw.get("slug") or "") or title)
        if not slug:
            issues.append(f"page {index + 1} has neither a usable slug nor a title")
            continue
        if slug in seen:
            # Two pages sharing a slug is not a warning: WordPress would make the
            # second one "slab-leak-repair-2" and the plan's own parent references
            # would then point at the wrong page.
            issues.append(
                f"duplicate slug {slug!r} (pages {seen[slug] + 1} and {index + 1}); "
                "WordPress would rename the second and the hierarchy would misresolve"
            )
            continue
        seen[slug] = index

        planned.append(PlannedPage(
            slug=slug,
            title=title or slug.replace("-", " ").title(),
            content=str(raw.get("content") or ""),
            elementor_data=str(raw.get("elementor_data") or ""),
            template=str(raw.get("template") or ""),
            parent_slug=slugify(str(raw.get("parent_slug") or "")),
            menu_order=int(raw.get("menu_order") or 0),
            in_menu=bool(raw.get("in_menu", True)),
        ))

    by_slug = {p.slug: p for p in planned}

    for page in planned:
        if page.parent_slug and page.parent_slug not in by_slug:
            issues.append(
                f"page {page.slug!r} names parent {page.parent_slug!r}, which is not in "
                "this plan; WordPress would silently create it at the top level"
            )

    cycle = _first_cycle(by_slug)
    if cycle:
        issues.append(f"parent cycle: {' -> '.join(cycle)}")

    for page in planned:
        depth = _depth(page, by_slug)
        if depth > MAX_MENU_DEPTH:
            notes.append(
                f"{page.slug!r} sits {depth} levels deep; most themes render two levels "
                "of navigation, so it will exist but may not appear in the menu"
            )

    front = slugify(front_page_slug)
    if front and front not in by_slug:
        issues.append(f"front page {front!r} is not one of the planned pages")
    if not front:
        notes.append("no front page requested; the site's existing front page is untouched")
    if menu_location and not any(p.in_menu for p in planned):
        notes.append("a menu location was given but no page is marked in_menu")
    if not planned:
        issues.append("the plan contains no pages")

    return SitePlan(
        pages=tuple(planned), menu_name=menu_name, menu_location=menu_location,
        front_page_slug=front, status=status,
        replace_existing_menu=replace_existing_menu,
        issues=tuple(issues), notes=tuple(notes),
    )


def _depth(page: PlannedPage, by_slug: dict[str, PlannedPage]) -> int:
    depth = 1
    seen = {page.slug}
    cursor = page
    while cursor.parent_slug and cursor.parent_slug in by_slug:
        cursor = by_slug[cursor.parent_slug]
        if cursor.slug in seen:
            return depth  # a cycle is reported separately; do not spin here
        seen.add(cursor.slug)
        depth += 1
    return depth


def _first_cycle(by_slug: dict[str, PlannedPage]) -> list[str] | None:
    """The first parent cycle found, as a readable chain.

    A cycle would make the plugin's parent resolution loop forever, so it has to be
    caught here rather than discovered on a client's server.
    """
    for start in by_slug:
        seen: list[str] = []
        cursor: str | None = start
        while cursor and cursor in by_slug:
            if cursor in seen:
                return [*seen[seen.index(cursor):], cursor]
            seen.append(cursor)
            cursor = by_slug[cursor].parent_slug or None
    return None
