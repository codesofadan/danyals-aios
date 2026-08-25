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

from app.services.design_system import DesignSystem, extract
from app.services.elementor_replica import (
    UnknownSettingError,
    build_tree,
    mobile_text_positions,
    responsive_heading_sizes,
    to_json,
    validate_tree,
)
from app.services.layout_infer import InferredPage, infer_layout
from app.services.replica_css import generate


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

    tree = build_tree(
        page, ds,
        responsive_heading_sizes(captures),
        mobile_text_positions(captures),
    )
    try:
        validate_tree(tree)
    except UnknownSettingError as exc:
        # A bug in OUR emitter, not in the page. Publishing a tree the editor would
        # silently mangle is the one thing this pipeline must never do.
        result.note(f"refused by the oracle: {exc}")
        return result

    payload = {
        "title": title or (capture.title or "Replicated page"),
        "slug": slug or "",
        "post_type": "page",
        "content": "<p>Replicated by AIOS. Open in Elementor to edit.</p>",
        "elementor_data": to_json(tree),
        "elementor_edit_mode": "builder",
        "design_css": generate(page, ds, capture.css_vars),
    }
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
