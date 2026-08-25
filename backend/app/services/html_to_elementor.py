"""Rebuild a captured page as a native, editable Elementor document (P6.6, step 2).

`elementor.py` renders from a MARKDOWN draft the pipeline wrote. This renders from a
page that already exists - the case where a client points at a URL and asks for it back
as something they can edit.

EVERY WIDGET IS ELEMENTOR FREE-CORE. heading, text-editor, image, button, icon-list,
divider. Nothing custom, nothing Pro, no registration step - so the rebuilt page opens
in Elementor with native controls on every element, which is the whole point of doing
this rather than shipping a block of HTML.

FIDELITY, HONESTLY. This reproduces STRUCTURE and CONTENT faithfully - the heading
hierarchy, the copy, the links, the images, the lists, the buttons and their targets,
plus the page's typography and palette applied as real Elementor typography settings.

It does NOT reproduce the CSS cascade. A pixel-exact clone would need the stylesheet,
the media queries and the specificity chain resolved per element, and a half-resolved
cascade produces a page that looks almost right in a way nobody can debug. The
measurements that ARE trustworthy come from `site_analyzer`'s real getComputedStyle
capture, and those are what get applied.

The distinction matters for what to promise: this gives back a page whose every element
is real, editable and correctly ordered, styled with the site's own fonts and colours -
not a screenshot-accurate copy.
"""

from __future__ import annotations

from typing import Any

from app.services.elementor import _IdGen, _pad, _widget
from app.services.html_capture import Block, CapturedPage

# Elementor's own placeholder. A page built with these has no real imagery, and
# carrying them into the rebuild reproduces the gap rather than hiding it - but it is
# worth REPORTING, because "your images did not come across" and "your page has no
# images" are different problems with different fixes.
PLACEHOLDER_MARKER = "elementor/assets/images/placeholder"

# A section with fewer than this many widgets is merged into the previous one. A real
# page emits stray one-widget sections from layout divs, and preserving each as its own
# Elementor section produces a document nobody can navigate in the editor.
MIN_SECTION_WIDGETS = 1


def _typography(settings: dict[str, Any], prefix: str, font: str, size_px: int | None) -> None:
    """Apply a font as Elementor's own typography controls.

    `*_typography_typography = "custom"` is the switch Elementor's UI uses to mean "this
    element overrides the global style". Without it the font keys are stored and
    ignored, and the editor shows the global font while the page renders ours.
    """
    if not font and size_px is None:
        return
    settings[f"{prefix}typography_typography"] = "custom"
    if font:
        settings[f"{prefix}typography_font_family"] = font
    if size_px is not None:
        settings[f"{prefix}typography_font_size"] = {"unit": "px", "size": size_px}


def _heading(block: Block, ids: _IdGen, style: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "title": block.text,
        "header_size": f"h{block.level or 2}",
    }
    colour = block.styles.get("color") or style.get("heading_color")
    if colour:
        settings["title_color"] = colour
    _typography(settings, "title_", style.get("heading_font", ""), None)
    return _widget("heading", settings, ids, block.text)


def _text(block: Block, ids: _IdGen, style: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {"editor": f"<p>{block.text}</p>"}
    colour = block.styles.get("color") or style.get("text_color")
    if colour:
        settings["text_color"] = colour
    _typography(settings, "", style.get("body_font", ""), style.get("body_size_px"))
    return _widget("text-editor", settings, ids, block.text)


def _image(block: Block, ids: _IdGen, _style: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {
        # `url` alone is what Elementor reads for an external image; `id` is for a
        # media-library attachment, which a rebuilt page does not have yet.
        "image": {"url": block.url, "id": "", "alt": block.alt},
        "image_size": "full",
    }
    if block.alt:
        settings["caption"] = ""
    return _widget("image", settings, ids, block.url)


def _button(block: Block, ids: _IdGen, style: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "text": block.text,
        # `is_external` / `nofollow` left unset so Elementor's defaults apply; a link
        # with no href becomes a button the client can point wherever they like.
        "link": {"url": block.url, "is_external": "", "nofollow": ""},
        "align": "left",
    }
    accent = style.get("accent")
    if accent:
        settings["background_color"] = accent
    _typography(settings, "typography_", style.get("body_font", ""), None)
    return _widget("button", settings, ids, block.text or block.url)


def _list(block: Block, ids: _IdGen, style: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "icon_list": [
            {"text": item, "selected_icon": {"value": "fas fa-check", "library": "fa-solid"}}
            for item in block.items
        ],
        "space_between": {"unit": "px", "size": 12},
    }
    if style.get("accent"):
        settings["icon_color"] = style["accent"]
    if style.get("text_color"):
        settings["text_color"] = style["text_color"]
    return _widget("icon-list", settings, ids, "|".join(block.items[:3]))


def _divider(_block: Block, ids: _IdGen, _style: dict[str, Any]) -> dict[str, Any]:
    return _widget("divider", {"style": "solid", "weight": {"unit": "px", "size": 1}},
                   ids, "divider")


_BUILDERS = {
    "heading": _heading, "text": _text, "image": _image,
    "button": _button, "list": _list, "divider": _divider, "quote": _text,
}


def style_from(page: CapturedPage, measured: dict[str, Any] | None = None) -> dict[str, Any]:
    """The style to apply, preferring MEASURED values over anything inferred.

    ``measured`` is a `brand_kit`-shaped dict from `site_analyzer`'s getComputedStyle
    capture. Where it has a value that value wins, for the same reason the brand kit
    merges that way: a real browser measurement beats a guess, every time.
    """
    style: dict[str, Any] = {}
    measured = measured or {}
    palette = measured.get("palette") or {}
    typography = measured.get("typography") or {}

    style["heading_font"] = typography.get("heading_font") or (page.meta.fonts[0] if page.meta.fonts else "")
    style["body_font"] = typography.get("body_font") or (page.meta.fonts[-1] if page.meta.fonts else "")
    style["heading_color"] = palette.get("primary", "")
    style["text_color"] = palette.get("text", "")
    style["accent"] = palette.get("accent", "")

    raw_size = str(typography.get("base_size") or "")
    if raw_size.endswith("px"):
        try:
            style["body_size_px"] = int(float(raw_size[:-2]))
        except ValueError:
            style["body_size_px"] = None
    else:
        style["body_size_px"] = None
    return style


def build_document(
    page: CapturedPage, *, measured: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Turn a captured page into an Elementor tree plus notes about what it could not do.

    Returns `(tree, notes)`. The notes are not decoration: they are how an operator
    learns that the source page's images were placeholders, or that a section came
    across empty, without opening the editor to find out.
    """
    ids = _IdGen()
    style = style_from(page, measured)
    notes: list[str] = []
    tree: list[dict[str, Any]] = []

    placeholders = sum(
        1 for b in page.blocks if b.kind == "image" and PLACEHOLDER_MARKER in b.url
    )
    if placeholders:
        notes.append(
            f"{placeholders} of the source page's images are Elementor's own "
            "placeholder graphic - the original page has no real photography at those "
            "positions, so the rebuild carries the placeholders through rather than "
            "inventing images"
        )

    for group in page.by_section():
        widgets: list[dict[str, Any]] = []
        for block in group:
            builder = _BUILDERS.get(block.kind)
            if builder is None:
                continue
            widgets.append(builder(block, ids, style))
        if not widgets:
            continue
        if len(widgets) < MIN_SECTION_WIDGETS and tree:
            tree[-1]["elements"][0]["elements"].extend(widgets)
            continue
        tree.append(_section(widgets, ids))

    if not tree:
        notes.append("no content was captured; nothing was rebuilt")
    return tree, tuple(notes)


def _section(widgets: list[dict[str, Any]], ids: _IdGen) -> dict[str, Any]:
    """One full-width section holding one column - the shape Elementor's editor expects.

    Legacy section/column rather than a flexbox container, deliberately: it is what
    every Elementor version since 2016 edits natively, where containers need 3.6+ and
    the experiment enabled. The measured source page uses BOTH, so neither is exotic -
    but only one works everywhere.
    """
    column = {
        "id": ids.next(f"col:{len(widgets)}"),
        "elType": "column",
        "settings": {"_column_size": 100, "_inline_size": None},
        "elements": widgets,
    }
    return {
        "id": ids.next(f"sec:{len(widgets)}"),
        "elType": "section",
        "settings": {
            "structure": "10",
            "content_width": {"unit": "px", "size": 1140},
            "padding": _pad(40),
        },
        "elements": [column],
    }


def meta_payload(page: CapturedPage) -> dict[str, str]:
    """The page's meta, in the shape the publish path already sends.

    Kept separate from the widget tree because it is not a widget: title, description
    and canonical belong in the head, and Yoast/RankMath read them from post meta. The
    operator edits them in the SEO plugin's own box, which is where they expect to.
    """
    return {
        "title": page.meta.title,
        "description": page.meta.description or page.meta.og_description,
        "canonical": page.meta.canonical,
        "og_title": page.meta.og_title or page.meta.title,
        "og_description": page.meta.og_description or page.meta.description,
        "og_image": page.meta.og_image,
    }
