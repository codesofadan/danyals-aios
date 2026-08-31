"""URL in, editable Elementor page out - the pipeline as one callable (stage 6).

Every piece exists and is tested; this is the composition, so replication runs from a
URL through the worker rather than by an operator's hands. Steps, each of which may
degrade and says so:

    capture (3 viewports) -> design system -> layout -> tree (+responsive facts)
    -> validate against the oracle -> component stylesheet -> push via the plugin

COPYRIGHT GATE, INHERITED NOT INVENTED: replication carries the source page's actual
copy. `site_builder` already restricts copy-carrying flows to `existing_site` (the
client's own property); this takes the same rule as a parameter the caller must
assert, rather than trusting a URL to prove ownership.

Total: never raises for pipeline reasons. The result names each stage's outcome so a
failure reads "capture degraded: <why>" rather than a stack trace from a worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from app.services.design_system import DesignSystem, extract
from app.services.elementor_replica import (
    UnknownSettingError,
    build_navbar,
    build_tree,
    mobile_text_positions,
    responsive_heading_sizes,
    to_json,
    validate_tree,
)
from app.services.layout_infer import InferredPage, infer_layout, infer_navbar
from app.services.replica_capability import TargetCapability
from app.services.replica_css import generate
from app.services.site_design import profile_from_design_system


class ReplicaPublisher(Protocol):
    """The plugin door (`WordPressPluginPublisher` satisfies it)."""

    def publish(self, payload: dict[str, Any]) -> Any: ...


@dataclass
class ReplicaResult:
    ok: bool = False
    url: str = ""
    post_id: int | None = None
    preview_url: str = ""
    sections: int = 0
    widgets: int = 0
    notes: list[str] = field(default_factory=list)
    # The measured design, as the CONTENT pipeline's profile shape. The replicator has
    # always measured a richer design system than the content analyzer does and then
    # discarded it; carrying it out is what lets a replicated design drive generated
    # pages (QA 20) without a second Playwright capture of the same URL.
    design_profile: dict[str, Any] | None = None

    def note(self, text: str) -> None:
        self.notes.append(text)


def _serialize(node: Any) -> dict[str, Any]:
    return {
        "t": node.tag, "box": list(node.box), "s": node.style,
        "cls": list(node.classes), "txt": node.text, "eid": node.element_id,
        "href": node.href, "src": node.src, "alt": node.alt,
        **({"scrim": node.scrim} if node.scrim else {}),
        "kids": [_serialize(k) for k in node.children],
    }


def replicate(
    url: str,
    *,
    publisher: ReplicaPublisher,
    title: str | None = None,
    slug: str | None = None,
    owner_confirmed_source: bool = False,
    capture: Any | None = None,
) -> ReplicaResult:
    """Rebuild ``url`` as a draft Elementor page on the connected site.

    ``owner_confirmed_source`` is the copyright gate: the CALLER asserts the source
    belongs to the client. Without it nothing is captured, because a rebuild carries
    the source's actual words and imagery.

    ``capture`` accepts a pre-made `ReplicaCapture` so tests and re-runs skip the
    browser; absent, the live page is measured at three viewports.
    """
    result = ReplicaResult(url=url)
    if not owner_confirmed_source:
        result.note(
            "refused: replication carries the source page's own copy and imagery, so "
            "the caller must assert the client owns the source (owner_confirmed_source)"
        )
        return result

    if capture is None:
        from integrations.replica_capture import capture_replica

        capture = capture_replica(url)
    for n in capture.notes:
        result.note(f"capture: {n}")
    desktop = capture.desktop
    if desktop is None or desktop.root is None:
        result.note("capture degraded: no desktop viewport was measured")
        return result

    raw = _serialize(desktop.root)
    captures = {
        vp.viewport: _serialize(vp.root)
        for vp in capture.viewports
        if vp.root is not None and vp.viewport != "desktop"
    }

    nodes: list[dict[str, Any]] = []

    def flatten(n: dict[str, Any]) -> None:
        nodes.append(n)
        for k in n.get("kids") or []:
            flatten(k)

    flatten(raw)

    page: InferredPage = infer_layout(raw, viewport_width=desktop.width)
    for n in page.notes:
        result.note(f"layout: {n}")
    if not page.sections:
        result.note("layout degraded: no sections were inferred; nothing to publish")
        return result

    ds: DesignSystem = extract(nodes, css_vars=capture.css_vars)
    if not ds.is_grounded:
        result.note("design system is ungrounded (few measured values); styling will be thin")
    # Capture it for the content pipeline before the rebuild consumes it. `container_px`
    # comes from the INFERRED PAGE, not from `ds` - `extract` was called without a
    # container above, so `ds.container_px` is 0 here and reading it would silently
    # emit the default width for every site.
    result.design_profile = profile_from_design_system(
        ds, container_px=page.container_px, notes=f"Replicated from {url}"
    ).as_dict()

    tree = build_tree(
        page, ds,
        responsive_heading_sizes(captures),
        mobile_text_positions(captures),
    )

    # THE SITE'S CHROME. A replica without the source's navbar and footer is a
    # torso - the owner's words. The header is RECOGNISED (logo / menu / CTA from
    # geometry and tags) and emitted as one editable section; the footer is a
    # normal multi-column region and rides the standard inference. Either may be
    # absent; the page publishes without it, and the note says so.
    # WHAT THIS TARGET CAN RENDER, asked before anything is emitted. A client with
    # Elementor Pro gets a real nav menu rather than the free-tier approximation;
    # a site whose plugin cannot answer falls back to the conservative free set.
    # Never guess upward: an unknown widget is stored and silently ignored by the
    # editor, so an over-ambitious tree renders a page with holes and no error.
    caps_raw: dict[str, Any] = {}
    getter = getattr(publisher, "capabilities", None)
    if callable(getter):
        try:
            caps_raw = getter() or {}
        except Exception as exc:  # a probe must never fail the rebuild
            result.note(f"capability probe failed: {type(exc).__name__}")
    capability = (TargetCapability.from_ping(caps_raw) if caps_raw
                  else TargetCapability.free_tier("the site did not report a widget registry"))
    result.note(f"capability: {capability.summary()}")
    for n in capability.notes:
        result.note(f"capability: {n}")

    chrome_used = False
    nav_used = False
    hdr = getattr(desktop, "header", None)
    if hdr is not None:
        nav = infer_navbar(_serialize(hdr), viewport_width=desktop.width)
        if nav is not None:
            for n in nav.notes:
                result.note(f"navbar: {n}")
            result.note(f"navbar recognised: {nav.layout} "
                        f"({len(nav.links)} links)")
            navbar, nav_notes = build_navbar(nav, ds, page.container_px, capability)
            for n in nav_notes:
                result.note(f"navbar: {n}")
            tree.insert(0, navbar)
            chrome_used = True
            nav_used = True
        else:
            result.note("a header was captured but no navbar was recognised in it")
    else:
        result.note("no header element was found on the source")
    ftr = getattr(desktop, "footer", None)
    if ftr is not None:
        ftr_raw = _serialize(ftr)
        footer_page = infer_layout(ftr_raw, viewport_width=desktop.width)
        if footer_page.sections:
            footer_secs = build_tree(footer_page, ds)
            _paint_footer_ground(footer_secs, ftr_raw)
            tree.extend(footer_secs)
            result.note(f"footer replicated: {len(footer_secs)} section(s)")
            chrome_used = True
        else:
            result.note("a footer was captured but no layout was inferred from it")
    else:
        result.note("no footer element was found on the source")

    # INTERNAL LINKS point at the replica's own site, not back at the source:
    # same-host URLs become path-relative, so sibling pages replicated at the
    # same slugs connect to each other.
    _localize_links(tree, url)
    try:
        validate_tree(tree)
    except UnknownSettingError as exc:
        # A bug in OUR emitter, not in the page. Publishing a tree the editor would
        # silently mangle is the one thing this pipeline must never do.
        result.note(f"refused by the oracle: {exc}")
        return result

    head = getattr(capture, "head", {}) or {}
    payload = {
        "title": title or (capture.title or "Replicated page"),
        "slug": slug or "",
        "post_type": "page",
        "content": "<p>Replicated by AIOS. Open in Elementor to edit.</p>",
        "elementor_data": to_json(tree),
        "elementor_edit_mode": "builder",
        "design_css": generate(page, ds, capture.css_vars,
                               body_bg=getattr(capture, "body_bg", ""),
                               has_navbar=nav_used),
    }
    # THE <head> FUNDAMENTALS travel with the page: the source's meta title and
    # description ARE the replica's (it is the same page), written through the
    # plugin into whichever SEO plugin the site runs. The canonical is NOT
    # copied - the source's canonical names the source's domain, and a replica
    # claiming it would be pointing search engines at someone else's URL;
    # WordPress emits the correct SELF-canonical on singular pages by itself.
    if head.get("title"):
        payload["meta_title"] = head["title"]
    if head.get("description"):
        payload["meta_description"] = head["description"]
    if chrome_used:
        # With the navbar and footer replicated ON the page, the theme's own
        # header/footer must not double up around them.
        payload["template"] = "elementor_canvas"

    try:
        pushed = publisher.publish(payload)
    except Exception as exc:
        result.note(f"publish failed: {type(exc).__name__}: {str(exc)[:140]}")
        return result

    result.ok = True
    result.post_id = getattr(pushed, "post_id", None)
    result.preview_url = getattr(pushed, "preview_url", "") or getattr(pushed, "url", "")
    result.sections = len(page.sections)
    result.widgets = to_json(tree).count('"widgetType"')
    return result


def _localize_links(tree: list[dict[str, Any]], source_url: str) -> int:
    """Rewrite same-host link URLs to path-relative, in place. Returns the count.

    A replica's internal links must not lead back to the source's domain: once
    sibling pages are replicated at matching slugs, path-relative links connect
    them on the NEW site. Cross-domain links (socials, maps, tel/mailto) are left
    exactly as captured. Image/file sources are NOT rewritten - the media still
    lives on the source until sideloading happens.
    """
    host = urlparse(source_url).netloc.lower().removeprefix("www.")
    if not host:
        return 0
    rewritten = 0

    def rewrite(value: str) -> str:
        nonlocal rewritten
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            return value
        if parsed.netloc.lower().removeprefix("www.") != host:
            return value
        rewritten += 1
        path = parsed.path or "/"
        return path + (f"?{parsed.query}" if parsed.query else "")

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            link = obj.get("link")
            if isinstance(link, dict) and isinstance(link.get("url"), str):
                link["url"] = rewrite(link["url"])
            # button/link settings carry {"link": {...}}; a bare "url" key is an
            # image source or background and stays pointed at the real file
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(tree)
    return rewritten


def _paint_footer_ground(sections: list[dict[str, Any]], footer_root: dict[str, Any]) -> None:
    """Give unpainted footer sections the footer element's OWN ground, in place.

    A footer's dark look usually lives on the <footer> element itself; the bands
    inside it are transparent. The band inference reads each band's own paint, so
    every replicated footer section arrived white and the footer's white text
    vanished into it. Sections that measured their own background keep it.
    """
    import re as _re

    from app.services.design_system import to_hex

    style = footer_root.get("s") or {}
    ground = to_hex(style.get("backgroundColor", ""))
    image = ""
    m = _re.search(r'url\(["\']?([^"\')]+)', style.get("backgroundImage", "") or "")
    if m:
        image = m.group(1)
    if not ground and not image:
        return
    for sec in sections:
        settings = sec.setdefault("settings", {})
        if settings.get("background_color") or settings.get("background_image"):
            continue
        if ground:
            settings["background_background"] = "classic"
            settings["background_color"] = ground
        if image and not image.startswith("data:"):
            settings["background_background"] = "classic"
            settings["background_image"] = {"url": image, "id": ""}
            settings["background_size"] = "cover"
            settings["background_position"] = "center center"
