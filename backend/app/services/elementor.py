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
from dataclasses import dataclass
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
# RICH page composer: slot the draft's content into a BLUEPRINT's ordered sections
# and render each as a CLASSIC, styled Elementor component (hero, icon-box grid,
# accordion FAQ, testimonial cards, CTA banner) - a real, editable page, not flat
# text wrapped in <section>s. Used when the worker resolves a blueprint (a chosen
# TEMPLATE or the ANALYZED site); the simple builder above is the no-blueprint path.
# --------------------------------------------------------------------------- #
# A default CLASSIC palette / tokens so a template-only page (no analyzed profile)
# still renders premium; an analyzed profile OVERRIDES these so the page mirrors the
# real site.
_CLASSIC_PALETTE: dict[str, str] = {
    "primary": "#0f172a", "secondary": "#475569", "background": "#ffffff",
    "text": "#1e293b", "accent": "#2563eb",
}
_CLASSIC_TOKENS: dict[str, Any] = {"container_px": 1160, "spacing_px": 64, "button_radius": 8}
_GRID_COLS_MAX = 3  # icon-box / card grids cap at 3 columns (stack within on overflow)

# Heading keywords -> the section KIND a generated <h2> block most likely fills, so a
# draft's FAQ / testimonials / pricing / process block lands in the RIGHT template slot
# (most-specific first). Anything unmatched is generic "body" prose.
_CHUNK_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("faq", ("faq", "frequently asked", "question")),
    ("testimonials", ("testimonial", "what clients say", "what customers", "reviews", "what our")),
    ("pricing", ("pricing", "price", "packages", "plans", "cost")),
    ("process", ("how it works", "how we work", "our process", "the process", "what to expect", "steps")),
    ("benefits", ("benefit", "why choose", "why work", "advantage", "why us")),
    ("features", ("features", "what's included", "what you get", "included", "what we offer")),
    ("proof", ("proof", "results", "case stud", "evidence", "track record")),
    ("about", ("about",)),
    ("cta", ("get started", "get in touch", "next step", "ready to", "contact us", "book ")),
)


def _classify_chunk(heading: str) -> str:
    low = (heading or "").lower()
    for kind, kws in _CHUNK_KEYWORDS:
        if any(kw in low for kw in kws):
            return kind
    return "body"


def _first_sentence(text: str, *, max_words: int = 26) -> str:
    """A short hero sub-headline: the first sentence, capped to ``max_words`` words."""
    clean = re.sub(r"\s+", " ", (text or "").strip())
    head = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)[0] if clean else ""
    words = head.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


@dataclass
class _Chunk:
    heading: str
    blocks: list[dict[str, Any]]
    kind: str = "body"


def _parse_content(draft_md: str) -> tuple[list[dict[str, Any]], list[_Chunk]]:
    """Split the draft into the LEAD (H1 + intro + hero image, before the first H2) and
    an ordered list of H2 :class:`_Chunk`s (each classified to a likely section kind)."""
    lead: list[dict[str, Any]] = []
    chunks: list[_Chunk] = []
    current: _Chunk | None = None
    for block in _parse_blocks(draft_md or ""):
        if block["type"] == "heading" and int(block["level"]) == 2:
            current = _Chunk(heading=str(block["text"]), blocks=[])
            current.kind = _classify_chunk(current.heading)
            chunks.append(current)
        elif current is None:
            lead.append(block)
        else:
            current.blocks.append(block)
    return lead, chunks


# --- content extractors (bullets -> cards, FAQ pairs) --------------------------
def _split_card(text: str) -> tuple[str, str]:
    """Split a bullet into a card (title, description): ``**Title** — desc`` /
    ``Title: desc`` / ``Title — desc``, else ("", the whole line)."""
    bold = _BOLD_RE.match(text.strip())
    if bold:
        rest = text.strip()[bold.end():].lstrip(" -:").strip()
        return bold.group(1).strip(), rest
    for sep in (": ", " - "):
        if sep in text:
            title, _, rest = text.partition(sep)
            if len(title.split()) <= 8:
                return title.strip(), rest.strip()
    return "", text.strip()


def _chunk_cards(chunk: _Chunk) -> list[tuple[str, str]]:
    """The (title, description) cards a grid section renders - from the chunk's bullet
    items, else its ``### `` sub-headings + following prose, else its paragraphs."""
    cards: list[tuple[str, str]] = []
    for block in chunk.blocks:
        if block["type"] == "list":
            for item in block.get("items", []):
                if str(item).strip():
                    cards.append(_split_card(str(item)))
    if cards:
        return cards
    title = ""
    for block in chunk.blocks:
        if block["type"] == "heading" and int(block["level"]) >= 3:
            title = str(block["text"]).strip()
        elif block["type"] == "paragraph" and str(block["text"]).strip():
            cards.append((title, str(block["text"]).strip()))
            title = ""
    return cards


def _chunk_faq(chunk: _Chunk) -> list[tuple[str, str]]:
    """(question, answer) pairs from an FAQ chunk: each ``### `` is a question, the
    prose that follows is its answer."""
    pairs: list[tuple[str, str]] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        nonlocal question, answer
        if question and answer:
            pairs.append((question, " ".join(answer).strip()))
        question, answer = None, []

    for block in chunk.blocks:
        if block["type"] == "heading" and int(block["level"]) >= 3:
            flush()
            question = str(block["text"]).strip()
        elif block["type"] == "paragraph" and question is not None:
            answer.append(str(block["text"]).strip())
        elif block["type"] == "list" and question is not None:
            answer.extend(str(i) for i in block.get("items", []) if str(i).strip())
    flush()
    return pairs


# --- classic Elementor widget builders (free core widgets only) ----------------
def _heading_widget(
    text: str, level: int, ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, align: str = "", color: str = "", size_px: int = 0,
) -> dict[str, Any]:
    settings: dict[str, Any] = {"title": text, "header_size": f"h{level}"}
    settings["title_color"] = color or palette["primary"]
    if align:
        settings["align"] = align
    heading_font = (tokens or {}).get("heading_font")
    if heading_font or size_px:
        settings["typography_typography"] = "custom"
    if heading_font:
        settings["typography_font_family"] = heading_font
    if size_px:
        settings["typography_font_size"] = {"unit": "px", "size": size_px}
        settings["typography_font_weight"] = "700"
    return _widget("heading", settings, ids, f"{level}:{text}")


def _button_widget(
    label: str, url: str, ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, align: str = "center", on_accent: bool = False,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "text": label, "link": {"url": url or "#"}, "align": align,
        "button_background_color": palette["background"] if on_accent else palette["accent"],
        "button_text_color": palette["accent"] if on_accent else palette["background"],
    }
    radius = (tokens or {}).get("button_radius", 8)
    settings["border_radius"] = {
        "unit": "px", "top": radius, "right": radius, "bottom": radius, "left": radius,
        "isLinked": True,
    }
    body_font = (tokens or {}).get("body_font")
    if body_font:
        settings["typography_typography"] = "custom"
        settings["typography_font_family"] = body_font
    return _widget("button", settings, ids, f"{label}|{url}")


def _iconbox_widget(
    title: str, desc: str, ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "selected_icon": {"value": "fas fa-check-circle", "library": "fa-solid"},
        "title_text": title or (desc[:48] if desc else "Highlight"),
        "description_text": desc if title else "",
        "position": "top",
        "primary_color": palette["accent"],
        "title_color": palette["primary"],
        "description_color": palette["text"],
    }
    heading_font = (tokens or {}).get("heading_font")
    if heading_font:
        settings["title_typography_typography"] = "custom"
        settings["title_typography_font_family"] = heading_font
    return _widget("icon-box", settings, ids, f"{title}|{desc}")


def _accordion_widget(
    pairs: list[tuple[str, str]], ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None
) -> dict[str, Any]:
    tabs = [
        {
            "_id": ids.next(f"faq:{q}")[:7],
            "tab_title": q,
            "tab_content": f"<p>{_inline(a)}</p>",
        }
        for q, a in pairs
    ]
    settings: dict[str, Any] = {
        "tabs": tabs,
        "title_color": palette["primary"],
        "tab_active_color": palette["accent"],
        "icon_color": palette["accent"],
    }
    return _widget("accordion", settings, ids, "".join(q for q, _ in pairs))


def _quote_widget(
    quote: str, ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None
) -> dict[str, Any]:
    return _text_widget(f"<blockquote>{_inline(quote)}</blockquote>", ids, palette, tokens)


# --- section / column assembly -------------------------------------------------
def _column(
    widgets: list[dict[str, Any]], ids: _IdGen, *, size: int, seed: str,
    settings: dict[str, Any] | None = None, inner: bool = False,
) -> dict[str, Any]:
    col_settings: dict[str, Any] = {"_column_size": size}
    if settings:
        col_settings.update(settings)
    return {
        "id": ids.next(f"{'inner-' if inner else ''}column:{seed}"),
        "elType": "column",
        "settings": col_settings,
        "elements": widgets,
    }


def _grid_columns(
    items: list[dict[str, Any]], ids: _IdGen, seed: str, *, cols: int
) -> list[dict[str, Any]]:
    """Distribute widgets round-robin into ``cols`` equal columns (a classic grid that
    grows vertically rather than shrinking each cell)."""
    cols = max(1, min(cols, _GRID_COLS_MAX, len(items)))
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(cols)]
    for i, widget in enumerate(items):
        buckets[i % cols].append(widget)
    size = max(1, 100 // cols)
    return [_column(b, ids, size=size, seed=f"{seed}:{i}") for i, b in enumerate(buckets)]


def _kind_classes(kind: str, variant: str) -> str:
    cls = f"aios-{_slug(kind)}"
    if variant:
        cls += f" aios-layout-{_slug(variant)}"
    return cls


def _section(
    columns: list[dict[str, Any]], ids: _IdGen, *, kind: str, variant: str,
    palette: dict[str, str], tokens: dict[str, Any] | None,
    background: str = "", centered: bool = False, hero: bool = False,
) -> dict[str, Any]:
    """Assemble one styled top-level Elementor section from ready columns, carrying the
    ``aios-<kind> aios-layout-<variant>`` classes + palette/token styling."""
    settings: dict[str, Any] = {"_css_classes": _kind_classes(kind, variant)}
    if background:
        settings["background_background"] = "classic"
        settings["background_color"] = background
    if tokens is not None:
        container_px = tokens.get("container_px")
        if container_px is not None:
            settings["content_width"] = {"unit": "px", "size": container_px}
        spacing = tokens.get("spacing_px")
        pad = max(72, spacing or 0) if hero else (spacing if spacing is not None else 48)
        settings["padding"] = _pad(pad)
    if centered:
        settings["content_position"] = "center"
        settings["text_align"] = "center"
    return {
        "id": ids.next(f"section:{kind}:{variant}"),
        "elType": "section",
        "settings": settings,
        "elements": columns,
    }


def _inner_grid(
    cards: list[tuple[str, str]], ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None
) -> dict[str, Any]:
    """An inner-section of icon-box cards in up to 3 equal columns (a real grid)."""
    widgets = [_iconbox_widget(t, d, ids, palette, tokens) for t, d in cards]
    columns = _grid_columns(widgets, ids, "grid", cols=_GRID_COLS_MAX)
    return {
        "id": ids.next("inner:grid"),
        "elType": "section",
        "isInner": True,
        "settings": {"gap": "extended"},
        "elements": columns,
    }


# --- per-kind section renderers (return 0..1 top-level sections) ---------------
def _render_hero(
    lead: list[dict[str, Any]], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str, cta: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The hero: big H1 + a short sub-headline + a primary CTA button, with the hero
    image beside it (split) or below (centered). Returns (section, leftover_intro_blocks)
    - the intro paragraphs NOT used in the hero, so they flow into the next section."""
    title = ""
    paragraphs: list[str] = []
    image: dict[str, Any] | None = None
    for block in lead:
        if block["type"] == "heading" and int(block["level"]) == 1 and not title:
            title = str(block["text"]).strip()
        elif block["type"] == "image" and image is None:
            image = block
        elif block["type"] == "paragraph" and str(block["text"]).strip():
            paragraphs.append(str(block["text"]).strip())
    if not title and not paragraphs and image is None:
        return None, []
    centered = variant == "centered" or "split" not in variant
    align = "center" if centered else "left"
    text_widgets: list[dict[str, Any]] = []
    if title:
        text_widgets.append(
            _heading_widget(title, 1, ids, palette, tokens, align=align, size_px=44)
        )
    subhead = _first_sentence(paragraphs[0]) if paragraphs else ""
    if subhead:
        text_widgets.append(
            _text_widget(f"<p>{_inline(subhead)}</p>", ids, palette, tokens)
        )
    if cta and cta.get("button_label"):
        text_widgets.append(
            _button_widget(
                str(cta["button_label"]), str(cta.get("button_url") or "#"),
                ids, palette, tokens, align=align,
            )
        )
    leftover = [{"type": "paragraph", "text": p} for p in paragraphs[1:]]
    if image is not None and not centered:
        # A balanced split: the heading/copy column and the image column are equal (50/50)
        # so the hero reads as a clean, editorial two-up - not a lopsided text wall.
        cols = [
            _column(text_widgets, ids, size=50, seed="hero-text"),
            _column(
                [_widget("image", {"image": {"url": image["url"], "alt": image.get("alt", "")}},
                         ids, str(image["url"]))],
                ids, size=50, seed="hero-img",
            ),
        ]
    else:
        widgets = list(text_widgets)
        if image is not None:
            widgets.append(
                _widget("image", {"image": {"url": image["url"], "alt": image.get("alt", "")},
                                  "align": "center"}, ids, str(image["url"]))
            )
        cols = [_column(widgets, ids, size=100, seed="hero")]
    section = _section(
        cols, ids, kind=kind, variant=variant, palette=palette, tokens=tokens,
        background=palette["background"], centered=centered, hero=True,
    )
    return section, leftover


def _render_grid(
    heading: str, cards: list[tuple[str, str]], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not cards:
        return None
    inner: list[dict[str, Any]] = []
    if heading:
        inner.append(_heading_widget(heading, 2, ids, palette, tokens, align="center"))
    inner.extend(images or [])  # a section image sits under the heading, above the grid
    inner.append(_inner_grid(cards, ids, palette, tokens))
    col = _column(inner, ids, size=100, seed=f"grid:{kind}")
    return _section([col], ids, kind=kind, variant=variant, palette=palette, tokens=tokens)


def _render_steps(
    heading: str, cards: list[tuple[str, str]], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not cards:
        return None
    widgets: list[dict[str, Any]] = []
    if heading:
        widgets.append(_heading_widget(heading, 2, ids, palette, tokens, align="center"))
    widgets.extend(images or [])  # a section image sits under the heading, above the steps
    icon_items = [
        {
            "_id": ids.next(f"step:{i}")[:7],
            "text": f"<strong>Step {i}.</strong> " + _inline((t + " - " + d) if t and d else (t or d)),
            "selected_icon": {"value": "fas fa-arrow-right", "library": "fa-solid"},
        }
        for i, (t, d) in enumerate(cards, start=1)
    ]
    widgets.append(
        _widget(
            "icon-list",
            {"icon_list": icon_items, "icon_color": palette["accent"],
             "text_color": palette["text"], "space_between": {"unit": "px", "size": 14}},
            ids, heading or "steps",
        )
    )
    return _section([_column(widgets, ids, size=100, seed=f"steps:{kind}")], ids,
                    kind=kind, variant=variant, palette=palette, tokens=tokens)


def _render_faq(
    heading: str, pairs: list[tuple[str, str]], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
) -> dict[str, Any] | None:
    if not pairs:
        return None
    widgets = [
        _heading_widget(heading or "Frequently asked questions", 2, ids, palette, tokens, align="center"),
        _accordion_widget(pairs, ids, palette, tokens),
    ]
    return _section([_column(widgets, ids, size=100, seed="faq")], ids,
                    kind=kind, variant=variant, palette=palette, tokens=tokens)


def _render_testimonials(
    heading: str, quotes: list[str], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
) -> dict[str, Any] | None:
    quotes = [q for q in quotes if str(q).strip()]
    if not quotes:
        return None
    head_widgets = [_heading_widget(heading or "What clients say", 2, ids, palette, tokens, align="center")]
    card_widgets = [_quote_widget(q, ids, palette, tokens) for q in quotes[:_GRID_COLS_MAX * 2]]
    inner = {
        "id": ids.next("inner:quotes"),
        "elType": "section", "isInner": True, "settings": {"gap": "extended"},
        "elements": _grid_columns(card_widgets, ids, "quotes", cols=_GRID_COLS_MAX),
    }
    col = _column([*head_widgets, inner], ids, size=100, seed="testimonials")
    return _section([col], ids, kind=kind, variant=variant, palette=palette, tokens=tokens)


def _render_cta(
    cta: dict[str, Any] | None, ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
) -> dict[str, Any] | None:
    if not cta:
        return None
    heading = str(cta.get("heading") or "").strip()
    text = str(cta.get("text") or "").strip()
    label = str(cta.get("button_label") or "").strip()
    url = str(cta.get("button_url") or "").strip() or "#"
    if not (heading or text or label):
        return None
    widgets: list[dict[str, Any]] = []
    if heading:
        widgets.append(
            _heading_widget(heading, 2, ids, palette, tokens, align="center",
                            color=palette["background"])
        )
    if text:
        w = _text_widget(f"<p>{_inline(text)}</p>", ids, palette, tokens)
        w["settings"]["text_color"] = palette["background"]
        w["settings"]["align"] = "center"
        widgets.append(w)
    if label:
        widgets.append(_button_widget(label, url, ids, palette, tokens, align="center", on_accent=True))
    col = _column(widgets, ids, size=100, seed="cta")
    return _section([col], ids, kind=kind, variant=variant, palette=palette, tokens=tokens,
                    background=palette["accent"], centered=True)


def _render_prose(
    heading: str, blocks: list[dict[str, Any]], ids: _IdGen, palette: dict[str, str],
    tokens: dict[str, Any] | None, *, kind: str, variant: str,
) -> dict[str, Any] | None:
    widgets: list[dict[str, Any]] = []
    if heading:
        widgets.append(_heading_widget(heading, 2, ids, palette, tokens))
    for block in blocks:
        widget = _build_widget(block, ids, palette, tokens)
        if widget is not None:
            widgets.append(widget)
    if not widgets:
        return None
    return _section([_column(widgets, ids, size=100, seed=f"prose:{kind}")], ids,
                    kind=kind, variant=variant, palette=palette, tokens=tokens)


_GRID_KINDS: frozenset[str] = frozenset({"benefits", "features", "services", "usp"})
_SPECIAL_KINDS: frozenset[str] = frozenset({"hero", "faq", "testimonials", "cta"})


def _render_content(
    kind: str, variant: str, heading: str, blocks: list[dict[str, Any]],
    ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Render a generic content section by its kind: a grid of icon-box cards
    (benefits/features/services), a numbered step list (process), else classic prose."""
    chunk = _Chunk(heading=heading, blocks=blocks, kind=kind)
    # A grid/steps section drops the prose blocks (it renders cards), so its section image
    # would be lost - render it explicitly, under the heading, above the cards.
    images = [
        _widget("image", {"image": {"url": str(b.get("url") or ""), "alt": str(b.get("alt") or "")},
                          "align": "center"}, ids, str(b.get("url") or ""))
        for b in blocks if b.get("type") == "image" and str(b.get("url") or "").strip()
    ]
    if kind in _GRID_KINDS:
        cards = _chunk_cards(chunk)
        section = _render_grid(heading, cards, ids, palette, tokens, kind=kind, variant=variant, images=images)
        return section or _render_prose(heading, blocks, ids, palette, tokens, kind=kind, variant=variant)
    if kind == "process":
        cards = _chunk_cards(chunk)
        section = _render_steps(heading, cards, ids, palette, tokens, kind=kind, variant=variant, images=images)
        return section or _render_prose(heading, blocks, ids, palette, tokens, kind=kind, variant=variant)
    return _render_prose(heading, blocks, ids, palette, tokens, kind=kind, variant=variant)


def _compose_rich(
    draft_md: str, sections: list[dict[str, Any]], *,
    palette: dict[str, str], tokens: dict[str, Any] | None,
    cta: dict[str, Any] | None, testimonials: list[str],
) -> list[dict[str, Any]]:
    """Slot the draft into the blueprint's ordered sections + render each as a classic
    styled component.

    Two-pass assignment so content lands in the RIGHT section: (A) every ``<h2>`` block
    the draft classifies to a specific kind (FAQ / testimonials / pricing / process /
    benefits / …) is matched to the first section of THAT kind; (B) the remaining content
    sections are filled by the leftover blocks in document order. FAQ pairs render as an
    accordion, testimonials as cards, the derived CTA as a banner. Any overflow folds into
    the ``absorb`` section (the blog body) or the last content section, so no generated
    copy is dropped. Chrome sections with no content are skipped (never fabricated).
    Always returns a non-empty tree."""
    ids = _IdGen()
    lead, chunks = _parse_content(draft_md)
    taken: set[int] = set()
    hero_idx = next((i for i, s in enumerate(sections) if s.get("kind") == "hero"), None)

    # --- consume the special-kind chunks into their dedicated pools ---
    faq_pairs: list[tuple[str, str]] = []
    for i, ch in enumerate(chunks):
        if ch.kind == "faq":
            faq_pairs = _chunk_faq(ch)
            taken.add(i)
            break
    quotes = [q for q in testimonials if str(q).strip()]
    if not quotes:
        for i, ch in enumerate(chunks):
            if ch.kind == "testimonials":
                quotes = [str(x) for b in ch.blocks if b["type"] == "list" for x in b.get("items", [])]
                taken.add(i)
                break
    for i, ch in enumerate(chunks):  # a CTA chunk is superseded by the derived CTA
        if ch.kind == "cta":
            taken.add(i)
            break

    # --- assign the remaining chunks to content sections (Pass A: by kind; B: in order) ---
    assigned: dict[int, _Chunk] = {}

    def free_section_of(kind: str) -> int | None:
        for i, s in enumerate(sections):
            if (
                i not in assigned and i != hero_idx and bool(s.get("content", True))
                and str(s.get("kind")) == kind and kind not in _SPECIAL_KINDS
            ):
                return i
        return None

    for i, ch in enumerate(chunks):
        if i in taken or ch.kind == "body":
            continue
        j = free_section_of(ch.kind)
        if j is not None:
            assigned[j] = ch
            taken.add(i)
    absorb_idx = next((i for i, s in enumerate(sections) if s.get("absorb")), None)
    remaining = [i for i in range(len(chunks)) if i not in taken]
    if absorb_idx is not None and bool(sections[absorb_idx].get("content", True)):
        # An absorb container (the blog ``body``): ALL leftover generic blocks flow here,
        # not spread across intro/proof/conclusion. Assign it the first leftover so it
        # renders; the rest fold in via the final merge below.
        if remaining:
            assigned[absorb_idx] = chunks[remaining[0]]
            taken.add(remaining[0])
    else:
        open_sections = [
            i for i, s in enumerate(sections)
            if i != hero_idx and bool(s.get("content", True))
            and str(s.get("kind")) not in _SPECIAL_KINDS and i not in assigned
        ]
        for j, i in zip(open_sections, remaining, strict=False):
            assigned[j] = chunks[i]
            taken.add(i)

    # --- render each section in blueprint order ---
    out: list[dict[str, Any]] = []
    out_at: dict[int, int] = {}
    intro_leftover: list[dict[str, Any]] = []
    for i, spec in enumerate(sections):
        kind = str(spec.get("kind") or "section").strip() or "section"
        variant = str(spec.get("layout") or "stacked").strip() or "stacked"
        section: dict[str, Any] | None = None
        if i == hero_idx:
            section, intro_leftover = _render_hero(
                lead, ids, palette, tokens, kind=kind, variant=variant, cta=cta
            )
        elif kind == "faq":
            section = _render_faq("", faq_pairs, ids, palette, tokens, kind=kind, variant=variant)
        elif kind == "testimonials":
            section = _render_testimonials("", quotes, ids, palette, tokens, kind=kind, variant=variant)
        elif kind == "cta":
            section = _render_cta(cta, ids, palette, tokens, kind=kind, variant=variant)
        elif i in assigned or intro_leftover:
            chunk = assigned.get(i)
            heading = chunk.heading if chunk else ""
            blocks = [*intro_leftover, *(chunk.blocks if chunk else [])]
            intro_leftover = []
            section = _render_content(kind, variant, heading, blocks, ids, palette, tokens)
        # chrome section with no assigned content -> skip (theme / plugin supplies it)
        if section is not None:
            out_at[i] = len(out)
            out.append(section)

    # --- fold any leftover chunks + unused intro into the absorb / last section ---
    leftover_blocks: list[dict[str, Any]] = list(intro_leftover)
    for i, ch in enumerate(chunks):
        if i not in taken:
            if ch.heading:
                leftover_blocks.append({"type": "heading", "level": 2, "text": ch.heading})
            leftover_blocks.extend(ch.blocks)
    if leftover_blocks:
        extra = _render_prose("", leftover_blocks, ids, palette, tokens, kind="body", variant="stacked")
        if extra is not None:
            target = out_at.get(absorb_idx) if absorb_idx is not None else None
            if target is None:
                target = len(out) - 1 if out else None
            if target is not None:
                out[target]["elements"][0]["elements"].extend(extra["elements"][0]["elements"])
            else:
                out.append(extra)

    if not out:  # nothing renderable at all -> a single valid text section
        out.append(
            _section([_column([_text_widget("", ids, palette, tokens)], ids, size=100, seed="empty")],
                     ids, kind="body", variant="stacked", palette=palette, tokens=tokens)
        )
    return out


# --------------------------------------------------------------------------- #
# Public builder.
# --------------------------------------------------------------------------- #
def build_elementor_data(
    draft_md: str,
    *,
    design_profile: dict[str, Any] | None = None,
    blueprint: list[dict[str, Any]] | None = None,
    cta: dict[str, Any] | None = None,
    testimonials: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the Elementor ``_elementor_data`` widget tree (a list of top-level
    sections) from a Markdown draft.

    Pure + deterministic (no clock / randomness). Two paths:

    * **RICH (a ``blueprint`` is supplied)** - the worker resolved a chosen TEMPLATE or
      the ANALYZED site into an ordered list of section specs (``{kind, layout,
      content, absorb}``). The draft's content is SLOTTED into those sections by kind
      (FAQ->faq, testimonials->testimonials, ...) and each is rendered as a CLASSIC,
      editable Elementor component (hero, icon-box grid, accordion, testimonial cards,
      CTA banner), styled with the profile's palette/fonts (or a classic default).
    * **SIMPLE (no blueprint)** - the legacy path: group by ``<h2>``, wrap each group in
      a named section, carry the ``design_profile`` palette. Empty input degrades to a
      single text section.
    """
    if blueprint:
        rich_palette = _palette_of(design_profile) or dict(_CLASSIC_PALETTE)
        rich_tokens = _design_tokens(design_profile) or dict(_CLASSIC_TOKENS)
        return _compose_rich(
            draft_md or "", blueprint, palette=rich_palette, tokens=rich_tokens,
            cta=cta, testimonials=list(testimonials or []),
        )

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


# --------------------------------------------------------------------------- #
# Render an EDITED page model (app.services.page_model.PageModel.to_dict()) to the
# Elementor tree, so the SAME model the dashboard editor edits is published BOTH as
# the styled HTML (page_model.model_to_html) AND as a drag-and-drop-editable Elementor
# page. Reuses the tested per-kind section renderers, so the output stays consistent
# with the draft-driven composer.
# --------------------------------------------------------------------------- #
def model_to_elementor(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the Elementor ``_elementor_data`` tree from a saved page-model dict. Only
    VISIBLE sections render; each is rendered by its kind. Always a non-empty tree."""
    design = model.get("design") if isinstance(model.get("design"), dict) else {}
    palette = _palette_of(design) or dict(_CLASSIC_PALETTE)
    tokens = _design_tokens(design) or dict(_CLASSIC_TOKENS)
    ids = _IdGen()
    out: list[dict[str, Any]] = []
    for sec in model.get("sections") or []:
        if not isinstance(sec, dict) or not sec.get("visible", True):
            continue
        section = _model_section_to_elementor(sec, ids, palette, tokens)
        if section is not None:
            out.append(section)
    if not out:
        out.append(
            _section([_column([_text_widget("", ids, palette, tokens)], ids, size=100, seed="empty")],
                     ids, kind="body", variant="stacked", palette=palette, tokens=tokens)
        )
    return out


def _model_images(sec: dict[str, Any], ids: _IdGen) -> list[dict[str, Any]]:
    return [
        _widget("image", {"image": {"url": str(im.get("url") or ""), "alt": str(im.get("alt") or "")},
                          "align": "center"}, ids, str(im.get("url") or ""))
        for im in (sec.get("images") or []) if isinstance(im, dict) and str(im.get("url") or "").strip()
    ]


def _model_section_to_elementor(
    sec: dict[str, Any], ids: _IdGen, palette: dict[str, str], tokens: dict[str, Any] | None
) -> dict[str, Any] | None:
    kind = str(sec.get("kind") or "prose")
    variant = str(sec.get("layout") or "stacked")
    heading = str(sec.get("heading") or "")
    data = _as_dict(sec.get("data"))
    images = _model_images(sec, ids)
    if kind == "hero":
        lead: list[dict[str, Any]] = [{"type": "heading", "level": 1, "text": heading}]
        if data.get("subhead"):
            lead.append({"type": "paragraph", "text": str(data["subhead"])})
        imgs = sec.get("images") or []
        if imgs and isinstance(imgs[0], dict) and imgs[0].get("url"):
            lead.append({"type": "image", "url": str(imgs[0]["url"]), "alt": str(imgs[0].get("alt") or "")})
        buttons = data.get("buttons") or []
        cta = None
        if buttons and isinstance(buttons[0], dict):
            cta = {"button_label": str(buttons[0].get("label") or ""),
                   "button_url": str(buttons[0].get("url") or "#")}
        section, _ = _render_hero(lead, ids, palette, tokens, kind=kind, variant=variant, cta=cta)
        return section
    if kind in _GRID_KINDS:
        cards = [(str(c.get("title") or ""), str(c.get("desc") or ""))
                 for c in (data.get("cards") or []) if isinstance(c, dict)]
        return _render_grid(heading, cards, ids, palette, tokens, kind=kind, variant=variant, images=images)
    if kind == "process":
        cards = [("", str(s)) for s in (data.get("steps") or []) if str(s).strip()]
        return _render_steps(heading, cards, ids, palette, tokens, kind=kind, variant=variant, images=images)
    if kind == "faq":
        pairs = [(str(f.get("q") or ""), str(f.get("a") or ""))
                 for f in (data.get("faq") or []) if isinstance(f, dict)]
        return _render_faq(heading, pairs, ids, palette, tokens, kind=kind, variant=variant)
    if kind == "testimonials":
        quotes = [str(q) for q in (data.get("quotes") or []) if str(q).strip()]
        return _render_testimonials(heading, quotes, ids, palette, tokens, kind=kind, variant=variant)
    if kind == "cta":
        btn = data.get("button") or {}
        cta = {"heading": heading, "text": str(data.get("text") or ""),
               "button_label": str(btn.get("label") or "Get in touch"), "button_url": str(btn.get("url") or "#")}
        return _render_cta(cta, ids, palette, tokens, kind=kind, variant=variant)
    # prose / proof / other: heading + the stored HTML as a text-editor widget + any image.
    widgets: list[dict[str, Any]] = []
    if heading:
        widgets.append(_heading_widget(heading, 2, ids, palette, tokens))
    widgets.extend(images)
    html = str(data.get("html") or "")
    if html:
        widgets.append(_text_widget(html, ids, palette, tokens))
    if not widgets:
        return None
    return _section([_column(widgets, ids, size=100, seed=f"prose:{kind}")], ids,
                    kind=kind, variant=variant, palette=palette, tokens=tokens)


def elementor_json_from_model(model: dict[str, Any]) -> str:
    """Compact JSON of :func:`model_to_elementor` - the ``_elementor_data`` for a saved,
    edited page model."""
    return json.dumps(model_to_elementor(model), separators=(",", ":"), ensure_ascii=False)


def elementor_json(
    draft_md: str,
    design_profile: dict[str, Any] | None = None,
    *,
    blueprint: list[dict[str, Any]] | None = None,
    cta: dict[str, Any] | None = None,
    testimonials: list[str] | None = None,
) -> str:
    """The compact JSON string of :func:`build_elementor_data` - exactly what WordPress
    stores in the ``_elementor_data`` post-meta."""
    tree = build_elementor_data(
        draft_md, design_profile=design_profile, blueprint=blueprint,
        cta=cta, testimonials=testimonials,
    )
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False)
