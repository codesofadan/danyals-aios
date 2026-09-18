"""The content-root descent, against a real browser.

THE DEFECT THIS PINS, measured on a live site. The in-page extractor walked
`main.children` directly, so a page builder that nests every section inside one
container - which Elementor, Divi and WPBakery all do - reported as a
SINGLE-section design. spotino.org (a live Elementor site with nine h2s)
captured as one `hero` and nothing else; after the descent it captures nine.

That is not cosmetic. The content pipeline builds a generated page to the
captured section grammar, so an under-read design silently yields a one-section
page - and the conformance check passes it, because it compares the page to the
same wrong capture.

No network: each case is a data: URL, so this pins the traversal itself rather
than whatever a third-party site happens to be serving today. Skips when the
`automation` extra or the Chromium binary is absent (both are optional - the
seams lazy-import Playwright and degrade without it).
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _sections_for(html: str) -> list[dict[str, Any]]:
    """Run the REAL extractor JS over `html` and return what it saw as sections."""
    pytest.importorskip("playwright", reason="needs the [automation] extra")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from integrations.site_analyzer import _EXTRACTOR_JS

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_content(html, wait_until="load")
                result = page.evaluate(_EXTRACTOR_JS)
            finally:
                browser.close()
    except PlaywrightError as exc:  # browser binary not installed
        pytest.skip(f"chromium unavailable: {type(exc).__name__}")
    return list(result.get("sections") or [])


def _block(title: str) -> str:
    """One section-sized block: tall enough to clear the 40px floor, with a heading."""
    return (
        f'<div class="elementor-section" style="min-height:200px">'
        f"<h2>{title}</h2><p>Body copy for {title}.</p></div>"
    )


_TITLES = ["Hero", "Services", "Proof", "Pricing", "FAQ", "Contact"]


def test_a_builder_wrapper_does_not_collapse_the_page_to_one_section() -> None:
    """The Elementor shape: <main> holds ONE wrapper, the sections are inside it.

    Re-inject by restoring `const main = ...` and dropping the descent loop, and
    this returns 1.
    """
    blocks = "".join(_block(t) for t in _TITLES)
    html = (
        "<html><body><main>"
        f'<div data-elementor-type="wp-page">{blocks}</div>'
        "</main></body></html>"
    )

    sections = _sections_for(html)

    assert len(sections) == len(_TITLES)
    assert [s["heading"] for s in sections] == _TITLES


def test_a_plain_page_is_unchanged_by_the_descent() -> None:
    """The guard against over-correcting: a page whose sections are already direct
    children of <main> must read exactly as it did before."""
    html = "<html><body><main>" + "".join(_block(t) for t in _TITLES) + "</main></body></html>"

    assert [s["heading"] for s in _sections_for(html)] == _TITLES


def test_nested_wrappers_are_followed_to_the_real_sections() -> None:
    """Some themes stack a theme wrapper outside the builder's own."""
    blocks = "".join(_block(t) for t in _TITLES)
    html = (
        "<html><body><main><div class='site'><div class='content'>"
        f'<div data-elementor-type="wp-page">{blocks}</div>'
        "</div></div></main></body></html>"
    )

    assert len(_sections_for(html)) == len(_TITLES)


def test_the_descent_stops_at_chrome_rather_than_stepping_into_it() -> None:
    """Descending into a <header>/<nav>/<footer> would hand the chrome guard the
    INSIDE of the element it is supposed to classify - the torso-replica failure
    in the other direction. A lone chrome child ends the walk."""
    html = (
        "<html><body><main><header style='min-height:200px'>"
        "<h2>Site header</h2><p>nav goes here</p></header></main></body></html>"
    )

    sections = _sections_for(html)

    # The header is reported as a section of role `header`, not descended into.
    assert [s["role"] for s in sections] == ["header"]


def test_a_single_leaf_child_does_not_empty_the_capture() -> None:
    """A wrapper with no element children is the end of the road: stepping into it
    would return zero sections, which downstream reads as 'this site has no
    design' rather than 'we could not find its sections'."""
    html = (
        "<html><body><main><div style='min-height:200px'>"
        "<h2>Only a leaf</h2></div></main></body></html>"
    )

    assert len(_sections_for(html)) == 1
