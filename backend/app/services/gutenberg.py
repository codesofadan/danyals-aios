"""Gutenberg block output: turn the SAME edited :class:`PageModel`
(``app.services.page_model``) that already renders to styled HTML and to an
Elementor widget tree into native WordPress Block Editor markup - so a page can
publish into a site with NO Elementor installed and still open fully editable in
the core Block Editor, not as one giant HTML/Classic block.

WHY THIS CONSUMES ``PageModel`` RATHER THAN RE-PARSING THE DRAFT: the hero/FAQ/
testimonial/CTA slotting + chunk-to-section assignment logic already lives ONCE in
``page_model.build_page_model`` (shared with the HTML renderer) and in
``elementor.build_elementor_data`` (the rich, blueprint-driven path). Re-deriving it
a third time here would fork that logic three ways. Instead this module mirrors
``elementor.model_to_elementor`` exactly - same per-kind switch, same input shape
(``PageModel.to_dict()``) - so "one PageModel, three renderers" holds: the dashboard
preview (HTML), an Elementor site (``elementor_json_from_model``), and a
Gutenberg-only site (this module) are always in lock-step.

Blocks carry the SAME ``aios-<kind> aios-layout-<variant>`` CSS classes the HTML +
Elementor renderers already use, so the EXISTING per-client ``design_css`` (already
generated + shipped alongside the body, see ``workers.tasks.content._design_css_text``)
continues to style a Gutenberg-rendered page with NO new CSS needed.

Pure + deterministic (stdlib only): no network, no DB, no clock, no randomness - a
given model always serialises to the same block markup, so it unit-tests trivially.
"""

from __future__ import annotations

import html as _html
import json
import re
from collections.abc import Callable
from typing import Any

_GRID_KINDS: frozenset[str] = frozenset({"benefits", "features", "services", "usp"})


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "section"


def _kind_classes(kind: str, variant: str) -> str:
    cls = f"aios-sec aios-{_slug(kind)}"
    if variant:
        cls += f" aios-layout-{_slug(variant)}"
    return cls


# --------------------------------------------------------------------------- #
# Core WP block emitters - each returns a comment-delimited block STRING whose
# innerHTML matches what the corresponding core block's own save() function
# produces for the given attributes, so the Block Editor opens it validated (no
# "attempt block recovery" prompt).
# --------------------------------------------------------------------------- #
def _attrs_json(attrs: dict[str, Any]) -> str:
    return " " + json.dumps(attrs, separators=(",", ":")) if attrs else ""


def paragraph_block(inline_html: str, *, align: str = "") -> str:
    attrs: dict[str, Any] = {"align": align} if align else {}
    cls = f' class="has-text-align-{align}"' if align else ""
    return f"<!-- wp:paragraph{_attrs_json(attrs)} -->\n<p{cls}>{inline_html}</p>\n<!-- /wp:paragraph -->"


def heading_block(inline_html: str, *, level: int = 2, align: str = "") -> str:
    attrs: dict[str, Any] = {"level": level}
    if align:
        attrs["textAlign"] = align
    cls = "wp-block-heading" + (f" has-text-align-{align}" if align else "")
    return (
        f"<!-- wp:heading{_attrs_json(attrs)} -->\n"
        f'<h{level} class="{cls}">{inline_html}</h{level}>\n'
        "<!-- /wp:heading -->"
    )


def list_block(items: list[str], *, ordered: bool = False) -> str:
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    attrs = {"ordered": True} if ordered else {}
    item_blocks = "\n".join(
        f"<!-- wp:list-item -->\n<li>{item}</li>\n<!-- /wp:list-item -->" for item in items
    )
    return (
        f"<!-- wp:list{_attrs_json(attrs)} -->\n"
        f'<{tag} class="wp-block-list">\n{item_blocks}\n</{tag}>\n'
        "<!-- /wp:list -->"
    )


def image_block(url: str, alt: str) -> str:
    if not url:
        return ""
    return (
        '<!-- wp:image {"sizeSlug":"large","linkDestination":"none"} -->\n'
        f'<figure class="wp-block-image size-large"><img src="{_esc(url)}" alt="{_esc(alt)}" title="{_esc(alt)}"/></figure>\n'
        "<!-- /wp:image -->"
    )


def button_block(label: str, url: str) -> str:
    if not label:
        return ""
    return (
        '<!-- wp:buttons -->\n<div class="wp-block-buttons">'
        '<!-- wp:button -->\n<div class="wp-block-button">'
        f'<a class="wp-block-button__link wp-element-button" href="{_esc(url or "#")}">{_esc(label)}</a>'
        "</div>\n<!-- /wp:button --></div>\n"
        "<!-- /wp:buttons -->"
    )

def quote_block(inline_html: str) -> str:
    return (
        '<!-- wp:quote -->\n<blockquote class="wp-block-quote">'
        f"<p>{inline_html}</p></blockquote>\n<!-- /wp:quote -->"
    )


def group_block(inner_blocks: list[str], *, class_name: str = "") -> str:
    """Wrap child blocks in a ``wp:group`` (a plain ``<div>``) carrying the
    ``aios-<kind>`` class, so section-level CSS keeps applying without any custom
    block."""
    inner = "\n".join(b for b in inner_blocks if b)
    attrs = {"className": class_name} if class_name else {}
    cls = "wp-block-group" + (f" {class_name}" if class_name else "")
    return f'<!-- wp:group{_attrs_json(attrs)} -->\n<div class="{cls}">\n{inner}\n</div>\n<!-- /wp:group -->'


def columns_block(columns: list[list[str]]) -> str:
    """``columns`` is a list of column-content lists (each already-built block
    strings); an empty ``columns`` degrades to nothing (never an empty shell)."""
    cols = [c for c in columns if any(b for b in c)]
    if not cols:
        return ""
    inner = "\n".join(
        '<!-- wp:column -->\n<div class="wp-block-column">\n'
        + "\n".join(b for b in col if b)
        + "\n</div>\n<!-- /wp:column -->"
        for col in cols
    )
    return f'<!-- wp:columns -->\n<div class="wp-block-columns">\n{inner}\n</div>\n<!-- /wp:columns -->'


# --------------------------------------------------------------------------- #
# Inline Markdown -> HTML (bold + links), mirroring ``elementor._inline`` so the
# SAME copy reads identically whichever renderer publishes it.
# --------------------------------------------------------------------------- #
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _inline(text: str) -> str:
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    return _BOLD_RE.sub(r"<strong>\1</strong>", text)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- #
# Per-kind section renderers (each returns ONE group block, or "" to skip).
# --------------------------------------------------------------------------- #
def _hero_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "")
    data = _as_dict(sec.get("data"))
    subhead = str(data.get("subhead") or "")
    buttons = data.get("buttons") or []
    images = sec.get("images") or []
    align = "center" if "centered" in variant or "split" not in variant else ""
    blocks = [heading_block(_inline(heading), level=1, align=align)] if heading else []
    if subhead:
        blocks.append(paragraph_block(_inline(subhead), align=align))
    for b in buttons[:1]:
        if isinstance(b, dict):
            blocks.append(button_block(str(b.get("label") or ""), str(b.get("url") or "#")))
    if images and isinstance(images[0], dict) and images[0].get("url"):
        blocks.append(image_block(str(images[0]["url"]), str(images[0].get("alt") or "")))
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _grid_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "")
    cards = _as_dict(sec.get("data")).get("cards") or []
    if not cards:
        return ""
    blocks = [heading_block(_inline(heading), align="center")] if heading else []
    columns: list[list[str]] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        title = str(c.get("title") or "")
        desc = str(c.get("desc") or "")
        col_blocks = []
        if title:
            col_blocks.append(heading_block(_inline(title), level=3))
        if desc:
            col_blocks.append(paragraph_block(_inline(desc)))
        columns.append(col_blocks)
    cols_block = columns_block(columns)
    if cols_block:
        blocks.append(cols_block)
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _steps_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "")
    steps = [str(s) for s in _as_dict(sec.get("data")).get("steps") or [] if str(s).strip()]
    if not steps:
        return ""
    blocks = [heading_block(_inline(heading), align="center")] if heading else []
    items = [f"<strong>Step {i}.</strong> {_inline(s)}" for i, s in enumerate(steps, start=1)]
    blocks.append(list_block(items, ordered=True))
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _faq_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "Frequently asked questions")
    pairs = _as_dict(sec.get("data")).get("faq") or []
    if not pairs:
        return ""
    blocks = [heading_block(_inline(heading), align="center")]
    for f in pairs:
        if not isinstance(f, dict):
            continue
        q = str(f.get("q") or "")
        a = str(f.get("a") or "")
        if q:
            blocks.append(heading_block(_inline(q), level=3))
        if a:
            blocks.append(paragraph_block(_inline(a)))
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _testimonials_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "What clients say")
    quotes = [str(q) for q in _as_dict(sec.get("data")).get("quotes") or [] if str(q).strip()]
    if not quotes:
        return ""
    blocks = [heading_block(_inline(heading), align="center")]
    blocks.extend(quote_block(_inline(q)) for q in quotes)
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _cta_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "")
    data = _as_dict(sec.get("data"))
    text = str(data.get("text") or "")
    btn = _as_dict(data.get("button"))
    if not (heading or text or btn.get("label")):
        return ""
    blocks = []
    if heading:
        blocks.append(heading_block(_inline(heading), align="center"))
    if text:
        blocks.append(paragraph_block(_inline(text), align="center"))
    if btn.get("label"):
        blocks.append(button_block(str(btn.get("label")), str(btn.get("url") or "#")))
    return group_block(blocks, class_name=_kind_classes(kind, variant))


def _prose_section(sec: dict[str, Any], *, kind: str, variant: str) -> str:
    heading = str(sec.get("heading") or "")
    html = str(_as_dict(sec.get("data")).get("html") or "")
    images = sec.get("images") or []
    blocks = [heading_block(_inline(heading))] if heading else []
    # ``html`` is already-built inline HTML (from page_model's prose renderer);
    # split on its own paragraph/list boundaries into individual blocks rather
    # than dropping the whole fragment into one opaque paragraph.
    for para in re.findall(r"<p>(.*?)</p>", html, flags=re.DOTALL):
        blocks.append(paragraph_block(para))
    for items_html in re.findall(r"<ul>(.*?)</ul>", html, flags=re.DOTALL):
        items = re.findall(r"<li>(.*?)</li>", items_html, flags=re.DOTALL)
        blocks.append(list_block(items))
    if not blocks and html:
        blocks.append(paragraph_block(html))
    if images and isinstance(images[0], dict) and images[0].get("url"):
        blocks.append(image_block(str(images[0]["url"]), str(images[0].get("alt") or "")))
    return group_block(blocks, class_name=_kind_classes(kind, variant))


_SectionRenderer = Callable[..., str]
_RENDERERS: dict[str, _SectionRenderer] = {
    "hero": _hero_section, "faq": _faq_section, "testimonials": _testimonials_section,
    "cta": _cta_section, "process": _steps_section,
}


def _section_to_block(sec: dict[str, Any]) -> str:
    kind = str(sec.get("kind") or "prose")
    variant = str(sec.get("layout") or "stacked")
    if kind in _GRID_KINDS:
        return _grid_section(sec, kind=kind, variant=variant)
    renderer: _SectionRenderer = _RENDERERS.get(kind, _prose_section)
    return renderer(sec, kind=kind, variant=variant)


def model_to_gutenberg(model: dict[str, Any]) -> str:
    """Build the ``post_content`` block markup from a saved page-model dict
    (``PageModel.to_dict()``). Only VISIBLE sections render; each is rendered by its
    kind, mirroring ``elementor.model_to_elementor`` section-for-section. Always
    returns non-empty markup (a bare paragraph block when nothing else renders)."""
    blocks: list[str] = []
    for sec in model.get("sections") or []:
        if not isinstance(sec, dict) or not sec.get("visible", True):
            continue
        block = _section_to_block(sec)
        if block:
            blocks.append(block)
    if not blocks:
        blocks.append(paragraph_block(""))
    return "\n\n".join(blocks)
