"""Elementor-editable page output: turn a reviewed Markdown draft into an Elementor
widget TREE so a published WordPress page opens fully editable (drag-and-drop) in
Elementor, not as flat HTML.

WordPress makes a page Elementor-editable via two post-meta values the companion
``AIOS Publisher`` plugin writes: ``_elementor_edit_mode = "builder"`` and
``_elementor_data`` = a JSON string of Elementor's widget tree. This module is the
PURE builder of that tree - no Celery, no DB, no network, no clock, no randomness -
so it is trivially unit-tested and byte-deterministic for a given draft.

The tree shape (``_elementor_data`` is a JSON ARRAY of top-level SECTIONS):

    section  {"id": <8hex>, "elType": "section", "settings": {...}, "elements": [column]}
    column   {"id": <8hex>, "elType": "column", "settings": {"_column_size": 100}, "elements": [widgets]}
    widget   {"id": <8hex>, "elType": "widget", "widgetType": "heading|text-editor|image|button", "settings": {...}}

Block mapping (Markdown -> widget):

* ``# / ## / ###``            -> ``heading``      ({"title": .., "header_size": "h1|h2|h3"})
* a paragraph line            -> ``text-editor``  ({"editor": "<p>..</p>"})
* a ``-`` bullet run          -> ``text-editor``  ({"editor": "<ul><li>..</li></ul>"})
* ``![alt](url)`` (own line)  -> ``image``        ({"image": {"url": .., "alt": ..}})
* ``[text](url)`` (own line)  -> ``button``       ({"text": .., "link": {"url": ..}})  (a CTA)

Sectioning:

* WITHOUT a design profile - blocks are split into sections at each heading of level
  <= 2 (an ``<h1>``/``<h2>`` starts a new section); content before the first such
  heading is the leading section. Empty / plain input degrades to a single text
  section (never an empty tree).
* WITH ``design_profile.layout.section_order`` - the same heading-grouped blocks are
  assigned, in order, to the named sections (overflow folds into the last named
  section, empty named sections are skipped), each section carries a
  ``aios-<name>`` CSS class, and the profile's ``palette`` colours are carried into
  the section / heading / text / button settings so the page echoes the site design.

Widget/column/section ids are a short SHA-1 of a monotonic position + the widget's
content - deterministic (same draft -> same ids) AND unique (the position disambiguates
identical content). NO ``Date``/``random`` is used, so the output is reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# --------------------------------------------------------------------------- #
# Inline Markdown -> HTML (links + bold), mirroring the worker's md_to_html so the
# Elementor text widgets read identically to the flat-HTML fallback body.
# --------------------------------------------------------------------------- #
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_ONLY_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """Convert inline Markdown links + bold to HTML (the draft is human-reviewed, so a
    full CommonMark pass is unnecessary - this matches ``content.md_to_html``)."""
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    return _BOLD_RE.sub(r"<strong>\1</strong>", text)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "section"


# --------------------------------------------------------------------------- #
# Deterministic, unique element ids (SHA-1 of a monotonic index + content).
# --------------------------------------------------------------------------- #
class _IdGen:
    """Hands out deterministic, unique 8-hex ids. The monotonic counter guarantees
    uniqueness (identical content at different positions still differs); starting the
    counter at 0 on every call makes the whole tree reproducible for a given draft."""

    def __init__(self) -> None:
        self._n = 0

    def next(self, content: str) -> str:
        self._n += 1
        return hashlib.sha1(f"{self._n}:{content}".encode()).hexdigest()[:8]


# --------------------------------------------------------------------------- #
# Draft -> blocks (a light, dependency-free block parse).
# --------------------------------------------------------------------------- #
def _parse_blocks(draft_md: str) -> list[dict[str, Any]]:
    """Parse the draft into ordered blocks: heading / paragraph / list / image / button.

    A ``-`` bullet run coalesces into one list block; a line that is ONLY an image is an
    image block; a line that is ONLY a link is a button (a CTA); everything else is a
    paragraph.
    """
    blocks: list[dict[str, Any]] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            blocks.append({"type": "list", "items": list(bullets)})
            bullets.clear()

    for line in draft_md.splitlines():
        s = line.strip()
        if not s:
            flush()
            continue
        img = _IMG_RE.fullmatch(s)
        if img:
            flush()
            blocks.append({"type": "image", "alt": img.group(1).strip(), "url": img.group(2).strip()})
        elif s.startswith("### "):
            flush()
            blocks.append({"type": "heading", "level": 3, "text": s[4:].strip()})
        elif s.startswith("## "):
            flush()
            blocks.append({"type": "heading", "level": 2, "text": s[3:].strip()})
        elif s.startswith("# "):
            flush()
            blocks.append({"type": "heading", "level": 1, "text": s[2:].strip()})
        elif s.startswith("- "):
            bullets.append(s[2:].strip())
        else:
            link = _ONLY_LINK_RE.fullmatch(s)
            if link:
                flush()
                blocks.append({"type": "button", "text": link.group(1).strip(), "url": link.group(2).strip()})
            else:
                flush()
                blocks.append({"type": "paragraph", "text": s})
    flush()
    return blocks


def _group_by_heading(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split blocks into groups, starting a new group at each heading of level <= 2.
    Content before the first such heading is the leading group."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for block in blocks:
        if block["type"] == "heading" and int(block["level"]) <= 2 and current:
            groups.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        groups.append(current)
    return groups


# --------------------------------------------------------------------------- #
# Design profile accessors (tolerant of a partial / absent profile).
# --------------------------------------------------------------------------- #
def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _palette_of(design_profile: dict[str, Any] | None) -> dict[str, str] | None:
    """The profile's palette as a flat ``{primary,secondary,background,text,accent}``
    string map, or ``None`` when no profile is supplied (plain, colourless output)."""
    if design_profile is None:
        return None
    p = _as_dict(design_profile.get("palette"))
    return {
        "primary": str(p.get("primary") or "#111827"),
        "secondary": str(p.get("secondary") or "#4b5563"),
        "background": str(p.get("background") or "#ffffff"),
        "text": str(p.get("text") or "#111827"),
        "accent": str(p.get("accent") or "#2563eb"),
    }


def _section_order_of(design_profile: dict[str, Any] | None) -> list[str]:
    """The profile's ordered section names, or ``[]`` when absent / malformed."""
    if design_profile is None:
        return []
    order = _as_dict(design_profile.get("layout")).get("section_order")
    if not isinstance(order, list):
        return []
    return [str(name).strip() for name in order if str(name).strip()]


def _px(value: Any) -> int | None:
    """The leading integer of a CSS size (``"1200px"`` -> ``1200``), or ``None``."""
    match = re.search(r"-?\d+", str(value or ""))
    return int(match.group()) if match else None


def _radius_px(style: str) -> int:
    """Map a button/card style phrase to a border-radius in px (mirrors the worker)."""
    s = (style or "").lower()
    if "pill" in s:
        return 999
    if "sharp" in s or "square" in s:
        return 0
    if "round" in s:
        return 8
    return 6


def _spacing_px(scale: str) -> int:
    """Map a spacing-scale phrase to a section vertical padding in px."""
    s = (scale or "").lower()
    if "compact" in s or "tight" in s or "dense" in s:
        return 24
    if "spacious" in s or "airy" in s or "generous" in s or "roomy" in s:
        return 72
    return 48


def _design_tokens(design_profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """Derive the non-colour design tokens (typography / layout / components) the
    Elementor widgets apply BEYOND palette + section order, or ``None`` when the profile
    is absent / carries none. Each token is independent: a missing sub-field is simply
    omitted (degrade), so a thin profile still works."""
    if design_profile is None:
        return None
    t = _as_dict(design_profile.get("typography"))
    ly = _as_dict(design_profile.get("layout"))
    c = _as_dict(design_profile.get("components"))
    tokens: dict[str, Any] = {}
    heading_font = str(t.get("heading_font") or "").strip()
    body_font = str(t.get("body_font") or "").strip()
    base_px = _px(t.get("base_size"))
    if heading_font:
        tokens["heading_font"] = heading_font
    if body_font:
        tokens["body_font"] = body_font
    if base_px is not None:
        tokens["base_px"] = base_px
    container_px = _px(ly.get("container_width"))
    if container_px is not None:
        tokens["container_px"] = container_px
    hero_style = str(ly.get("hero_style") or "").strip()
    if hero_style:
        tokens["hero_style"] = hero_style
    button_style = str(c.get("button_style") or "").strip()
    if button_style:
        tokens["button_radius"] = _radius_px(button_style)
    spacing = str(c.get("spacing_scale") or "").strip()
    if spacing:
        tokens["spacing_px"] = _spacing_px(spacing)
    card_style = str(c.get("card_style") or "").strip()
    if card_style:
        tokens["card_style"] = card_style
    return tokens or None


# --------------------------------------------------------------------------- #
# Block -> widget builders.
# --------------------------------------------------------------------------- #
def _widget(widget_type: str, settings: dict[str, Any], ids: _IdGen, id_seed: str) -> dict[str, Any]:
    return {
        "id": ids.next(f"{widget_type}:{id_seed}"),
        "elType": "widget",
        "widgetType": widget_type,
        "settings": settings,
    }


def _text_widget(
    html: str, ids: _IdGen, palette: dict[str, str] | None, tokens: dict[str, Any] | None
) -> dict[str, Any]:
    settings: dict[str, Any] = {"editor": html}
    if palette is not None:
        settings["text_color"] = palette["text"]
    if tokens is not None:
        body_font = tokens.get("body_font")
        base_px = tokens.get("base_px")
        if body_font or base_px is not None:
            settings["typography_typography"] = "custom"
        if body_font:
            settings["typography_font_family"] = body_font
        if base_px is not None:
            settings["typography_font_size"] = {"unit": "px", "size": base_px}
    return _widget("text-editor", settings, ids, html)


def _build_widget(
    block: dict[str, Any],
    ids: _IdGen,
    palette: dict[str, str] | None,
    tokens: dict[str, Any] | None,
) -> dict[str, Any] | None:
    kind = block["type"]
    if kind == "heading":
        text = str(block["text"])
        if not text:
            return None
        settings: dict[str, Any] = {"title": text, "header_size": f"h{int(block['level'])}"}
        if palette is not None:
            settings["title_color"] = palette["primary"]
        if tokens is not None and tokens.get("heading_font"):
            settings["title_typography_typography"] = "custom"
            settings["title_typography_font_family"] = tokens["heading_font"]
        return _widget("heading", settings, ids, text)
    if kind == "paragraph":
        text = str(block["text"])
        if not text:
            return None
        return _text_widget(f"<p>{_inline(text)}</p>", ids, palette, tokens)
    if kind == "list":
        items = [str(i) for i in block.get("items", []) if str(i).strip()]
        if not items:
            return None
        html = "<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>"
        return _text_widget(html, ids, palette, tokens)
    if kind == "image":
        url = str(block.get("url") or "").strip()
        if not url:
            return None
        return _widget("image", {"image": {"url": url, "alt": str(block.get("alt") or "")}}, ids, url)
    if kind == "button":
        text = str(block.get("text") or "").strip()
        url = str(block.get("url") or "").strip()
        if not text or not url:
            return None
        settings = {"text": text, "link": {"url": url}}
        if palette is not None:
            settings["button_background_color"] = palette["accent"]
            settings["button_text_color"] = palette["background"]
        if tokens is not None:
            radius = tokens.get("button_radius")
            if radius is not None:
                settings["border_radius"] = {
                    "unit": "px", "top": radius, "right": radius,
                    "bottom": radius, "left": radius, "isLinked": True,
                }
            if tokens.get("body_font"):
                settings["typography_typography"] = "custom"
                settings["typography_font_family"] = tokens["body_font"]
        return _widget("button", settings, ids, f"{text}|{url}")
    return None


def _pad(value: int) -> dict[str, Any]:
    """An Elementor top/bottom padding control (px), used for section spacing + hero."""
    return {
        "unit": "px", "top": str(value), "right": "0",
        "bottom": str(value), "left": "0", "isLinked": False,
    }


def _wrap_section(
    widgets: list[dict[str, Any]],
    ids: _IdGen,
    *,
    name: str | None,
    palette: dict[str, str] | None,
    tokens: dict[str, Any] | None,
    is_hero: bool = False,
) -> dict[str, Any]:
    """Wrap widgets in a single 100%-width column inside a section, carrying the
    section name (as a ``aios-<slug>`` CSS class) + the palette background when present,
    plus the design tokens: the layout container width, the component spacing (section
    padding) + card styling, and a hero boost on the first section."""
    seed = name or ""
    column = {
        "id": ids.next(f"column:{seed}"),
        "elType": "column",
        "settings": {"_column_size": 100},
        "elements": widgets,
    }
    sec_settings: dict[str, Any] = {}
    if name:
        sec_settings["_css_classes"] = f"aios-{_slug(name)}"
    if palette is not None:
        sec_settings["background_background"] = "classic"
        sec_settings["background_color"] = palette["background"]
    if tokens is not None:
        container_px = tokens.get("container_px")
        if container_px is not None:
            sec_settings["content_width"] = {"unit": "px", "size": container_px}
        spacing_px = tokens.get("spacing_px")
        if is_hero and tokens.get("hero_style"):
            # The hero gets a bigger, deliberate frame; centre it when the profile says so.
            sec_settings["padding"] = _pad(max(64, spacing_px or 0))
            if "center" in str(tokens["hero_style"]).lower():
                sec_settings["content_position"] = "center"
        elif spacing_px is not None:
            sec_settings["padding"] = _pad(spacing_px)
        card_style = str(tokens.get("card_style") or "").lower()
        if not is_hero and card_style:
            if "shadow" in card_style:
                sec_settings["box_shadow_box_shadow_type"] = "yes"
            elif "border" in card_style or "outline" in card_style:
                sec_settings["border_border"] = "solid"
                sec_settings["border_width"] = {
                    "unit": "px", "top": "1", "right": "1",
                    "bottom": "1", "left": "1", "isLinked": True,
                }
    return {
        "id": ids.next(f"section:{seed}"),
        "elType": "section",
        "settings": sec_settings,
        "elements": [column],
    }


def _assign_to_named_sections(
    blocks: list[dict[str, Any]], names: list[str]
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Assign heading-grouped blocks to the ordered named sections; groups beyond the
    name count fold into the LAST named section (mirrors the publish path's
    ``_wrap_sections``)."""
    groups = _group_by_heading(blocks)
    n = len(names)
    buckets: list[list[dict[str, Any]]] = [[] for _ in names]
    for i, group in enumerate(groups):
        buckets[i if i < n else n - 1].extend(group)
    return list(zip(names, buckets, strict=True))


# --------------------------------------------------------------------------- #
# Public builder.
# --------------------------------------------------------------------------- #
def build_elementor_data(
    draft_md: str, *, design_profile: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Build the Elementor ``_elementor_data`` widget tree (a list of top-level
    sections) from a Markdown draft.

    Pure + deterministic (no clock / randomness). A ``design_profile`` with a
    ``layout.section_order`` groups the content into the named sections and carries the
    ``palette`` colours into the settings. Empty / plain input degrades to a single text
    section (never an empty tree).
    """
    blocks = _parse_blocks(draft_md or "")
    palette = _palette_of(design_profile)
    tokens = _design_tokens(design_profile)
    names = _section_order_of(design_profile)
    ids = _IdGen()

    grouped: list[tuple[str | None, list[dict[str, Any]]]]
    if names:
        grouped = [(name, group) for name, group in _assign_to_named_sections(blocks, names)]
    else:
        grouped = [(None, group) for group in _group_by_heading(blocks)]

    sections: list[dict[str, Any]] = []
    for index, (name, group) in enumerate(grouped):
        widgets = [w for w in (_build_widget(b, ids, palette, tokens) for b in group) if w is not None]
        if not widgets:
            continue  # skip an empty named section
        sections.append(
            _wrap_section(widgets, ids, name=name, palette=palette, tokens=tokens, is_hero=index == 0)
        )

    if not sections:
        # Empty / plain input (or nothing renderable): a single, valid text section.
        fallback_name = names[0] if names else None
        sections.append(
            _wrap_section(
                [_text_widget("", ids, palette, tokens)],
                ids, name=fallback_name, palette=palette, tokens=tokens, is_hero=True,
            )
        )
    return sections


def elementor_json(draft_md: str, design_profile: dict[str, Any] | None = None) -> str:
    """The compact JSON string of :func:`build_elementor_data` - exactly what WordPress
    stores in the ``_elementor_data`` post-meta."""
    tree = build_elementor_data(draft_md, design_profile=design_profile)
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False)
