"""What JavaScript changes, and whether Google's first pass can see the page.

The engine's crawler executes no JavaScript, so what it fetches IS Googlebot's
first pass. Firecrawl renders the same URL in a real browser. Everything here
compares the two, which is the only honest way to answer whether a page depends
on rendering to say what it is.

Google does render, eventually - so a JS-dependent page is not automatically
broken. It is *delayed and at risk*: the render queue is best-effort, it can lag
by days, and it is skipped entirely for some crawls. Every remediation here says
that rather than claiming the page is invisible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check

#: JUDGEMENT: below this share of its rendered text, a page's pre-render
#: document is not a usable version of the page. Not a Google threshold - Google
#: publishes none - it is the point at which the raw HTML stops carrying the
#: page's meaning.
RAW_TEXT_SHARE_POOR = 0.30
RAW_TEXT_SHARE_WARN = 0.70

#: Lighthouse flags a DOM past 1,400 nodes and treats 800 as the target.
DOM_NODES_WARN = 800
DOM_NODES_POOR = 1_400

_NODE = re.compile(r"<[a-zA-Z][^>\s/]*", re.ASCII)
_LAZY_IMG = re.compile(r'<img[^>]*loading\s*=\s*["\']lazy["\']', re.I)
_HIDDEN = re.compile(
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden|text-indent\s*:\s*-\d{4,}'
    r'|font-size\s*:\s*0(?:px|pt|em)?\b|\bhidden\b\s*(?:=|>)|opacity\s*:\s*0(?:\.0+)?\s*[;"\'])',
    re.I,
)


@dataclass
class RenderedPage:
    """One page seen twice: before JavaScript, and after.

    ``raw`` is what the engine's crawler fetched - Googlebot's first pass.
    ``rendered`` is the same URL through a real browser.
    """

    url: str
    raw_html: str = ""
    rendered_html: str = ""
    raw: Any = None       # ParsedHTML | None
    rendered: Any = None  # ParsedHTML | None
    error: str | None = None
    #: Set when the page was rendered on a mobile viewport.
    mobile: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.rendered_html) and self.rendered is not None and not self.error


def _words(parsed: Any) -> int:
    return int(getattr(parsed, "word_count", 0) or 0)


def _na(page: RenderedPage, reason: str, **ev: Any) -> Verdict:
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, "url": page.url, **ev})


def _unrendered(page: RenderedPage) -> Verdict | None:
    if page is None:
        return Verdict("n_a", 0.0, "info", 0.0, {"reason": "no page was rendered"})
    if not page.ok:
        return _na(page, page.error or "the page could not be rendered")
    if page.raw is None:
        return _na(page, "the pre-JavaScript document was not captured, so there is "
                         "nothing to compare the rendered page against")
    return None


def _text_share(page: RenderedPage) -> float | None:
    """How much of the rendered page's words exist BEFORE JavaScript."""
    after = _words(page.rendered)
    if after <= 0:
        return None
    return min(1.0, _words(page.raw) / after)


# --------------------------------------------------------------------------
# Does the page need JavaScript to say what it is?
# --------------------------------------------------------------------------

@check("TECH-028", scope="rendered")
def check_javascript_rendering(page: RenderedPage) -> Verdict:
    """TECH-028 - how much of the page exists before JavaScript runs."""
    if (na := _unrendered(page)) is not None:
        return na
    share = _text_share(page)
    ev = {"url": page.url, "words_before_js": _words(page.raw),
          "words_after_js": _words(page.rendered),
          "share_present_before_js": None if share is None else round(share, 3),
          "threshold_basis": "judgement; Google publishes no ratio"}
    if share is None:
        return _na(page, "the rendered page contained no text to compare", **ev)
    if share >= RAW_TEXT_SHARE_WARN:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if share >= RAW_TEXT_SHARE_POOR:
        return Verdict("warn", 6.0, "minor", 0.85, ev,
                       f"{round(share * 100)}% of this page's text is present before "
                       f"JavaScript runs. Google renders eventually, but the render queue "
                       f"is best-effort and can lag by days, so the rest is delayed rather "
                       f"than guaranteed.")
    return Verdict("fail", 3.0, "major", 0.85, ev,
                   f"Only {round(share * 100)}% of this page's text exists before "
                   f"JavaScript runs. Googlebot's first pass sees a near-empty page and the "
                   f"rest waits on a render queue that is best-effort and sometimes skipped. "
                   f"Server-render or pre-render the primary content.")


@check("TECH-031", scope="rendered")
def check_client_side_rendering(page: RenderedPage) -> Verdict:
    """TECH-031 - the title and H1 specifically.

    A page whose TITLE only exists after JavaScript is the worst version of this
    problem: the title is the headline in every search result, and the first
    pass has nothing to put there.
    """
    if (na := _unrendered(page)) is not None:
        return na
    raw_title = (getattr(page.raw, "title", None) or "").strip()
    rendered_title = (getattr(page.rendered, "title", None) or "").strip()
    raw_h1 = list(getattr(page.raw, "h1s", []) or [])
    rendered_h1 = list(getattr(page.rendered, "h1s", []) or [])
    ev = {"url": page.url,
          "title_before_js": bool(raw_title), "title_after_js": bool(rendered_title),
          "h1_before_js": len(raw_h1), "h1_after_js": len(rendered_h1)}
    missing = []
    if rendered_title and not raw_title:
        missing.append("the title")
    if rendered_h1 and not raw_h1:
        missing.append("the H1")
    if not missing:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    # NOT .capitalize() - it lowercases the rest of the string, turning "the H1"
    # into "the h1". Uppercase the first character only.
    phrase = " and ".join(missing)
    phrase = phrase[:1].upper() + phrase[1:]
    return Verdict("fail", 2.0, "major", 0.9, ev,
                   f"{phrase} only exists after JavaScript "
                   f"runs. Googlebot's first pass has nothing to use as the search-result "
                   f"headline, which suppresses indexation across every page built this way.")


@check("TECH-032", scope="rendered")
def check_dom_content_comparison(page: RenderedPage) -> Verdict:
    """TECH-032 - what rendering ADDS, itemised: links, images, structured data.

    TECH-028 answers "how much". This answers "which parts", which is what turns
    the finding into a fix.
    """
    if (na := _unrendered(page)) is not None:
        return na

    def _counts(parsed: Any) -> dict[str, int]:
        return {
            "links": len(getattr(parsed, "links", []) or []),
            "images": len(getattr(parsed, "images", []) or []),
            "schema_blocks": len(getattr(parsed, "schema_blocks", []) or []),
        }

    before, after = _counts(page.raw), _counts(page.rendered)
    added = {k: after[k] - before[k] for k in after}
    ev = {"url": page.url, "before_js": before, "after_js": after, "added_by_js": added}
    js_only = [k for k, v in added.items() if v > 0 and before[k] == 0]
    if not any(v > 0 for v in added.values()):
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if js_only:
        return Verdict("fail", 3.0, "major", 0.85, ev,
                       f"{', '.join(js_only)} exist ONLY after JavaScript - there are none "
                       f"in the first-pass HTML at all. Structured data and internal links "
                       f"added this way are discovered late or not at all.")
    return Verdict("warn", 7.0, "minor", 0.85, ev,
                   "JavaScript adds links, images or markup that the first-pass HTML does "
                   "not contain. They are found on the render pass rather than immediately.")


# --------------------------------------------------------------------------
# Hidden content
# --------------------------------------------------------------------------

def _hidden_verdict(page: RenderedPage, *, which: str) -> Verdict:
    if (na := _unrendered(page)) is not None:
        return na
    html = page.rendered_html if which == "rendered" else page.raw_html
    hits = _HIDDEN.findall(html or "")
    ev = {"url": page.url, "hidden_style_matches": len(hits), "examined": which}
    if not hits:
        return Verdict("pass", 10.0, "info", 0.6, ev)
    # JUDGEMENT: hidden elements are overwhelmingly legitimate - dropdowns,
    # tabs, modals, cookie banners. A count alone is NOT evidence of cloaking,
    # and reporting it as one would be the audit crying wolf. Say what it is.
    return Verdict("warn", 7.0, "minor", 0.5, ev,
                   f"{len(hits)} elements are hidden with CSS. Most hidden content is "
                   f"legitimate - menus, tabs, modals - and Google discounts rather than "
                   f"penalises it. Worth a look only if primary copy is among it.")


@check("ON-108", scope="rendered")
def check_hidden_content(page: RenderedPage) -> Verdict:
    """ON-108 - content hidden in the delivered HTML."""
    return _hidden_verdict(page, which="raw")


@check("TECH-033", scope="rendered")
def check_js_hidden_content(page: RenderedPage) -> Verdict:
    """TECH-033 - content hidden in the RENDERED DOM, after scripts have run."""
    return _hidden_verdict(page, which="rendered")


# --------------------------------------------------------------------------
# Weight and images
# --------------------------------------------------------------------------

@check("TECH-049", scope="rendered")
def check_dom_size(page: RenderedPage) -> Verdict:
    """TECH-049 - an excessive DOM.

    Thresholds are Lighthouse's own: 800 nodes is the target, 1,400 is where it
    flags the page, so a client sees the same number from both tools.
    """
    if (na := _unrendered(page)) is not None:
        return na
    nodes = len(_NODE.findall(page.rendered_html or ""))
    ev = {"url": page.url, "dom_nodes": nodes,
          "target_nodes": DOM_NODES_WARN, "flagged_above": DOM_NODES_POOR,
          "threshold_basis": "Lighthouse dom-size audit"}
    if nodes <= DOM_NODES_WARN:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if nodes <= DOM_NODES_POOR:
        return Verdict("warn", 7.0, "minor", 0.85, ev,
                       f"The rendered page holds {nodes:,} elements against a {DOM_NODES_WARN} "
                       f"target. Style and layout cost grows with the count.")
    return Verdict("fail", 4.0, "major", 0.85, ev,
                   f"The rendered page holds {nodes:,} elements, past the {DOM_NODES_POOR} "
                   f"Lighthouse flags at. Every style recalculation walks all of them, which "
                   f"shows up directly in interaction delay on mid-range phones.")


@check("TECH-034", scope="rendered")
def check_lazy_load_indexing(page: RenderedPage) -> Verdict:
    """TECH-034 - images that only appear after JavaScript.

    ``loading="lazy"`` is native and safe: Google handles it. The risk is a
    JS lazy-loader that leaves no ``src`` in the first-pass HTML, so the image
    is never discovered.
    """
    if (na := _unrendered(page)) is not None:
        return na
    raw_imgs = len(getattr(page.raw, "images", []) or [])
    rendered_imgs = len(getattr(page.rendered, "images", []) or [])
    native_lazy = len(_LAZY_IMG.findall(page.rendered_html or ""))
    js_only = max(0, rendered_imgs - raw_imgs)
    ev = {"url": page.url, "images_before_js": raw_imgs, "images_after_js": rendered_imgs,
          "images_only_after_js": js_only, "native_lazy_loading": native_lazy}
    if rendered_imgs == 0:
        return _na(page, "the page has no images", **ev)
    if js_only == 0:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    share = js_only / rendered_imgs
    return Verdict("fail" if share > 0.5 else "warn",
                   max(3.0, 10.0 - share * 10.0),
                   "minor", 0.85, ev,
                   f"{js_only} of {rendered_imgs} images have no source in the first-pass "
                   f"HTML. Native loading=\"lazy\" is safe and Google handles it; a "
                   f"JavaScript lazy-loader that leaves no src means those images may never "
                   f"be discovered for Image Search.")


# --------------------------------------------------------------------------
# Mobile
# --------------------------------------------------------------------------

@check("TECH-030", scope="rendered")
def check_mobile_rendering(page: RenderedPage) -> Verdict:
    """TECH-030 - the page as rendered on a phone.

    Google's index is mobile-only, so the mobile render is THE render. Reports
    n_a rather than guessing when the capture was desktop.
    """
    if (na := _unrendered(page)) is not None:
        return na
    if not page.mobile:
        return _na(page, "this page was rendered on a desktop viewport, so nothing can be "
                         "said about its mobile rendering",
                   rendered_viewport="desktop")
    viewport = (getattr(page.rendered, "viewport", None) or "").strip()
    words = _words(page.rendered)
    ev = {"url": page.url, "viewport_meta": viewport or None, "words_rendered": words,
          "context": "Google's index is mobile-only, so this IS the render that matters"}
    if not viewport:
        return Verdict("fail", 2.0, "critical", 0.9, ev,
                       "The page renders on a phone with no viewport meta tag, so it is laid "
                       "out at desktop width and then shrunk. Google indexes this rendering.")
    if words < 50:
        return Verdict("fail", 3.0, "critical", 0.9, ev,
                       f"The mobile render produced only {words} words. Google indexes the "
                       f"mobile version, so this is the version that ranks.")
    return Verdict("pass", 10.0, "info", 0.9, ev)


@check("TECH-065", scope="rendered")
def check_responsive_design(page: RenderedPage) -> Verdict:
    """TECH-065 - the markup-level responsive signals.

    Honest about its limit: without screenshots at several breakpoints this
    cannot say the layout *looks* right, only that the page declares the things
    a responsive layout needs. The evidence says so.
    """
    if (na := _unrendered(page)) is not None:
        return na
    html = page.rendered_html or ""
    viewport = (getattr(page.rendered, "viewport", None) or "").strip()
    has_media_query = "@media" in html
    has_srcset = "srcset=" in html or "<picture" in html.lower()
    fixed_width = bool(re.search(r'width\s*[:=]\s*["\']?\s*\d{4,}\s*(?:px)?', html))
    ev = {"url": page.url, "viewport_meta": viewport or None,
          "media_queries": has_media_query, "responsive_images": has_srcset,
          "fixed_width_over_1000px": fixed_width,
          "limit": "markup signals only - proving the LAYOUT works needs rendered "
                   "screenshots at several breakpoints, which this run does not capture"}
    problems = []
    if not viewport:
        problems.append("no viewport meta tag")
    if not has_media_query:
        problems.append("no CSS media queries")
    if fixed_width:
        problems.append("a fixed width over 1000px")
    if not problems:
        return Verdict("pass", 10.0, "info", 0.6, ev)
    return Verdict("fail" if not viewport else "warn",
                   max(3.0, 10.0 - 3.0 * len(problems)),
                   "major" if not viewport else "minor", 0.6, ev,
                   f"The page shows {', '.join(problems)}. On a mobile-only index these are "
                   f"the signals that decide whether the page is usable on a phone.")
