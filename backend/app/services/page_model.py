"""The canonical, EDITABLE page model - the single representation the dashboard live
editor edits and BOTH publish renderers consume, so "what you see is what is published".

A content job's draft + its resolved blueprint (a chosen TEMPLATE or the analyzed site)
are slotted ONCE into an ordered list of typed :class:`Section`s (hero, card grid,
numbered steps, accordion FAQ, testimonial cards, stat band, CTA banner, prose). That
:class:`PageModel`:

* renders to premium, self-contained styled HTML (:func:`model_to_html`) - the dashboard
  preview AND the published page body, so the preview is pixel-faithful to what ships;
* serialises to/from a plain JSON dict (:meth:`PageModel.to_dict` / :func:`page_model_from_dict`)
  so the React editor can load it, edit text / swap images / reorder + hide sections, and
  save it back; and
* feeds the Elementor renderer (``elementor.model_to_elementor``) so the SAME edited model
  is published as a drag-and-drop-editable Elementor tree too.

Pure + deterministic (stdlib only): no network, no DB, no clock, no randomness. The slot
logic reuses the parser primitives in ``app.services.elementor`` so the model and the
Elementor tree are built from ONE parse.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.elementor import (
    _chunk_cards,
    _chunk_faq,
    _classify_chunk,
    _parse_content,
)
from app.services.page_blueprints import SectionSpec, resolve_blueprint

# Section kinds rendered as a card GRID of (title, description) items.
GRID_KINDS: frozenset[str] = frozenset({"benefits", "features", "services", "usp"})
_SPECIAL: frozenset[str] = frozenset({"hero", "faq", "testimonials", "cta"})


# --------------------------------------------------------------------------- #
# The editable shapes.
# --------------------------------------------------------------------------- #
@dataclass
class Image:
    url: str = ""
    alt: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "alt": self.alt}


@dataclass
class Section:
    """One editable page section: its stable ``id`` (for the editor), its ``kind`` +
    ``layout`` variant (drives the rendered component), ``visible`` (the editor can hide
    it), an editable ``heading``, and a kind-specific ``data`` payload:

    * hero      -> {"subhead": str, "buttons": [{"label","url"}]}, images=[hero]
    * grid      -> {"cards": [{"icon","title","desc"}]}, optional images
    * steps     -> {"steps": [str, ...]}
    * faq       -> {"faq": [{"q","a"}]}
    * testimonials -> {"quotes": [str, ...]}
    * stats     -> {"stats": [{"n","l"}]}
    * cta       -> {"text": str, "button": {"label","url"}}
    * prose     -> {"html": "<p>...</p>"}, optional images
    """

    id: str
    kind: str
    layout: str = "stacked"
    heading: str = ""
    visible: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    images: list[Image] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "layout": self.layout,
            "heading": self.heading,
            "visible": self.visible,
            "data": self.data,
            "images": [i.to_dict() for i in self.images],
        }


@dataclass
class PageModel:
    """The whole editable page: an ordered list of :class:`Section`s + the design
    profile (palette / typography / components) the renderers style with + the page
    title. Round-trips through ``to_dict`` / :func:`page_model_from_dict`."""

    title: str = ""
    sections: list[Section] = field(default_factory=list)
    design: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "design": self.design,
            "sections": [s.to_dict() for s in self.sections],
        }


def _derive_cta_for(row: dict[str, Any]) -> dict[str, Any]:
    """A closing call-to-action from the job (best practice; always present). The button
    points at the client's own site when known."""
    sp = _as_dict(row.get("source_pack"))
    site = str(sp.get("wp_site_url") or sp.get("site_url") or "").strip() or "#"
    client = str(sp.get("client_name") or row.get("client_name") or "our team").strip() or "our team"
    topic = str(row.get("topic") or "your goals").strip() or "your goals"
    return {
        "heading": "Ready to take the next step?",
        "text": f"Talk to {client} about {topic} and get expert guidance tailored to you.",
        "button_label": "Get in touch",
        "button_url": site,
    }


def page_model_for_job(row: dict[str, Any]) -> PageModel:
    """Build the editable :class:`PageModel` for a content-job row: slot its draft into
    the resolved blueprint (analyzed site / chosen template / page-type default) with the
    job's design profile, testimonials, and a derived CTA. This is what the dashboard live
    editor loads (and what publish renders when no hand-edited model is saved)."""
    sp = _as_dict(row.get("source_pack"))
    profile = _as_dict(sp.get("design_profile")) or None
    template = str(sp.get("template") or "").strip() or None
    testimonials = [str(t) for t in (sp.get("testimonials") or []) if str(t).strip()]
    return build_page_model(
        str(row.get("draft_md") or ""),
        design_profile=profile,
        template=template,
        page_type=str(row.get("page_type") or "blog"),
        cta=_derive_cta_for(row),
        testimonials=testimonials,
        title=str(row.get("topic") or ""),
    )


def page_model_from_dict(raw: dict[str, Any]) -> PageModel:
    """Rebuild a :class:`PageModel` from the editor's saved JSON (tolerant of missing
    fields so a partial save still loads)."""
    sections: list[Section] = []
    for i, s in enumerate(raw.get("sections") or []):
        if not isinstance(s, dict):
            continue
        images = [
            Image(url=str(im.get("url", "")), alt=str(im.get("alt", "")))
            for im in (s.get("images") or []) if isinstance(im, dict)
        ]
        sections.append(
            Section(
                id=str(s.get("id") or f"s{i}"),
                kind=str(s.get("kind") or "prose"),
                layout=str(s.get("layout") or "stacked"),
                heading=str(s.get("heading") or ""),
                visible=bool(s.get("visible", True)),
                data=_as_dict(s.get("data")),
                images=images,
            )
        )
    return PageModel(
        title=str(raw.get("title") or ""),
        sections=sections,
        design=_as_dict(raw.get("design")),
    )


# --------------------------------------------------------------------------- #
# Build the model: slot the draft into the blueprint (two-pass, by-kind then order).
# --------------------------------------------------------------------------- #
def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _split_bold(text: str) -> tuple[str, str]:
    m = re.match(r"\*\*([^*]+)\*\*", text.strip())
    if m:
        rest = text.strip()[m.end():].lstrip(" -:").strip()
        return m.group(1).strip(), rest
    for sep in (": ", " - "):
        if sep in text:
            t, _, r = text.partition(sep)
            if len(t.split()) <= 8:
                return t.strip(), r.strip()
    return "", text.strip()


def _inline_html(text: str) -> str:
    s = _html.escape(text, quote=True)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def _first_sentence(text: str, *, max_words: int = 34) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    head = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)[0] if clean else ""
    words = head.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def _prose_html(blocks: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for b in blocks:
        if b["type"] == "paragraph" and str(b["text"]).strip():
            out.append(f"<p>{_inline_html(str(b['text']))}</p>")
        elif b["type"] == "list":
            items = "".join(f"<li>{_inline_html(str(i))}</li>" for i in b.get("items", []) if str(i).strip())
            if items:
                out.append(f"<ul>{items}</ul>")
    return "".join(out)


def _images_of(blocks: list[dict[str, Any]]) -> list[Image]:
    return [
        Image(url=str(b.get("url") or ""), alt=str(b.get("alt") or ""))
        for b in blocks if b.get("type") == "image" and str(b.get("url") or "").strip()
    ]


def build_page_model(
    draft_md: str,
    *,
    design_profile: dict[str, Any] | None,
    template: str | None,
    page_type: str,
    cta: dict[str, Any] | None = None,
    testimonials: list[str] | None = None,
    title: str = "",
) -> PageModel:
    """Slot the draft into the resolved blueprint and return the editable page model.

    Precedence (via ``page_blueprints.resolve_blueprint``): an explicit template wins,
    else the analyzed site's blueprint, else the page-type default. Content is matched to
    the RIGHT section by kind (FAQ->faq, testimonials->testimonials, ...) then filled in
    document order; a blog ``body`` absorbs the overflow. Chrome sections with no content
    are kept as HIDDEN placeholders so the editor can still turn them on."""
    specs: list[SectionSpec] = resolve_blueprint(
        design_profile=design_profile, template=template, page_type=page_type
    )
    if not specs:  # gbp_post / nothing to shape by: a single prose section
        lead0, chunks0 = _parse_content(draft_md)
        blocks = list(lead0)
        for c in chunks0:
            blocks.append({"type": "heading", "level": 2, "text": c.heading})
            blocks.extend(c.blocks)
        model = PageModel(title=title, design=_as_dict(design_profile))
        model.sections.append(
            Section(id="s0", kind="prose", layout="stacked", data={"html": _prose_html(blocks)},
                    images=_images_of(blocks))
        )
        return model

    lead, chunks = _parse_content(draft_md)
    for c in chunks:
        c.kind = _classify_chunk(c.heading)
    taken: set[int] = set()
    hero_idx = next((i for i, s in enumerate(specs) if s.kind == "hero"), None)

    faq_pairs: list[tuple[str, str]] = []
    for i, c in enumerate(chunks):
        if c.kind == "faq":
            faq_pairs = _chunk_faq(c)
            taken.add(i)
            break
    quotes = [q for q in (testimonials or []) if str(q).strip()]
    for i, c in enumerate(chunks):
        if c.kind == "testimonials":
            # Consume the testimonials chunk even when a list was supplied, so it never
            # ALSO folds into a later section as duplicate leftover copy.
            if not quotes:
                quotes = [str(x) for b in c.blocks if b["type"] == "list" for x in b.get("items", [])]
            taken.add(i)
            break
    for i, c in enumerate(chunks):
        if c.kind == "cta":
            taken.add(i)
            break

    assigned: dict[int, Any] = {}

    def free_of(kind: str) -> int | None:
        for i, s in enumerate(specs):
            if (i not in assigned and i != hero_idx and s.content
                    and s.kind == kind and kind not in _SPECIAL):
                return i
        return None

    for i, c in enumerate(chunks):
        if i in taken or c.kind == "body":
            continue
        j = free_of(c.kind)
        if j is not None:
            assigned[j] = c
            taken.add(i)
    absorb_idx = next((i for i, s in enumerate(specs) if s.absorb), None)
    remaining = [i for i in range(len(chunks)) if i not in taken]
    if absorb_idx is not None and specs[absorb_idx].content:
        if remaining:
            assigned[absorb_idx] = chunks[remaining[0]]
            taken.add(remaining[0])
    else:
        opens = [i for i, s in enumerate(specs)
                 if i != hero_idx and s.content and s.kind not in _SPECIAL and i not in assigned]
        for j, i in zip(opens, remaining, strict=False):
            assigned[j] = chunks[i]
            taken.add(i)

    # fold leftover chunks into the absorb/last content section
    leftover_blocks: list[dict[str, Any]] = []
    for i, c in enumerate(chunks):
        if i not in taken:
            leftover_blocks.append({"type": "heading", "level": 2, "text": c.heading})
            leftover_blocks.extend(c.blocks)

    cta = cta or {}
    model = PageModel(title=title, design=_as_dict(design_profile))
    intro_leftover: list[dict[str, Any]] = []
    for idx, s in enumerate(specs):
        sid = f"s{idx}"
        if idx == hero_idx:
            hero = _hero_section(sid, s, lead, cta)
            model.sections.append(hero.section)
            intro_leftover = hero.leftover
            continue
        if s.kind == "faq":
            model.sections.append(Section(
                sid, "faq", s.layout, heading=s.heading or "Frequently asked questions",
                visible=bool(faq_pairs), data={"faq": [{"q": q, "a": a} for q, a in faq_pairs]}))
            continue
        if s.kind == "testimonials":
            model.sections.append(Section(
                sid, "testimonials", s.layout, heading=s.heading or "What clients say",
                visible=bool(quotes), data={"quotes": list(quotes)}))
            continue
        if s.kind == "cta":
            model.sections.append(Section(
                sid, "cta", s.layout, heading=str(cta.get("heading") or s.heading or "Get started"),
                data={"text": str(cta.get("text") or ""),
                      "button": {"label": str(cta.get("button_label") or "Get in touch"),
                                 "url": str(cta.get("button_url") or "#")}}))
            continue
        chunk = assigned.get(idx)
        if chunk is None and not (idx == _first_content_idx(specs, hero_idx) and intro_leftover):
            # chrome / unfilled content section -> a hidden placeholder the editor can enable
            model.sections.append(Section(sid, s.kind, s.layout, heading=s.heading, visible=False))
            continue
        blocks = [*intro_leftover, *(chunk.blocks if chunk else [])]
        heading = chunk.heading if chunk else s.heading
        intro_leftover = []
        model.sections.append(_content_section(sid, s, heading, blocks))

    if leftover_blocks:
        target = next((s for s in reversed(model.sections)
                       if s.kind not in _SPECIAL and s.visible), None)
        extra_html = _prose_html(leftover_blocks)
        if target is not None and extra_html:
            target.data["html"] = str(target.data.get("html", "")) + extra_html
    return model


def _first_content_idx(specs: list[SectionSpec], hero_idx: int | None) -> int:
    for i, s in enumerate(specs):
        if i != hero_idx and s.content and s.kind not in _SPECIAL:
            return i
    return -1


@dataclass
class _HeroBuild:
    section: Section
    leftover: list[dict[str, Any]]


def _hero_section(sid: str, spec: SectionSpec, lead: list[dict[str, Any]], cta: dict[str, Any]) -> _HeroBuild:
    title = next((str(b["text"]) for b in lead if b["type"] == "heading" and int(b["level"]) == 1), "")
    paras = [str(b["text"]) for b in lead if b["type"] == "paragraph" and str(b["text"]).strip()]
    imgs = _images_of(lead)
    subhead = _first_sentence(paras[0]) if paras else ""
    buttons = []
    if cta.get("button_label"):
        buttons.append({"label": str(cta["button_label"]), "url": str(cta.get("button_url") or "#")})
    section = Section(
        sid, "hero", spec.layout, heading=title or spec.heading,
        data={"subhead": subhead, "buttons": buttons}, images=imgs[:1],
    )
    leftover = [{"type": "paragraph", "text": p} for p in paras[1:]]
    return _HeroBuild(section, leftover)


def _content_section(sid: str, spec: SectionSpec, heading: str, blocks: list[dict[str, Any]]) -> Section:
    kind = spec.kind
    images = _images_of(blocks)
    if kind in GRID_KINDS:
        cards = _chunk_cards_from_blocks(blocks)
        if cards:
            return Section(sid, kind, spec.layout or "grid", heading=heading,
                           data={"cards": cards}, images=images)
    if kind == "process":
        steps = [
            ((c["title"] + " " + c["desc"]).strip() if c["title"] else c["desc"])
            for c in _chunk_cards_from_blocks(blocks)
        ]
        if steps:
            return Section(sid, kind, spec.layout or "numbered-steps", heading=heading,
                           data={"steps": steps}, images=images)
    if kind == "proof":
        return Section(sid, kind, spec.layout, heading=heading,
                       data={"html": _prose_html(blocks)}, images=images)
    return Section(sid, kind or "prose", spec.layout, heading=heading,
                   data={"html": _prose_html(blocks)}, images=images)


def _chunk_cards_from_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    from app.services.elementor import _Chunk  # a light reuse of the card extractor

    cards = _chunk_cards(_Chunk(heading="", blocks=blocks))
    return [{"icon": "", "title": t, "desc": d} for t, d in cards]


# --------------------------------------------------------------------------- #
# HTML renderer: the premium, self-contained styled page (preview == published).
# --------------------------------------------------------------------------- #
_DEFAULTS = {
    "primary": "#0f172a", "secondary": "#475569", "background": "#ffffff",
    "text": "#334155", "accent": "#2563eb",
}


def _palette(design: dict[str, Any]) -> dict[str, str]:
    p = _as_dict(design.get("palette"))
    return {k: str(p.get(k) or _DEFAULTS[k]) for k in _DEFAULTS}


def _fonts(design: dict[str, Any]) -> tuple[str, str]:
    t = _as_dict(design.get("typography"))
    head = str(t.get("heading_font") or "Sora, system-ui, sans-serif")
    body = str(t.get("body_font") or "Inter, system-ui, sans-serif")
    return head, body


def _radius(design: dict[str, Any]) -> int:
    style = str(_as_dict(design.get("components")).get("button_style") or "").lower()
    if "pill" in style:
        return 999
    if "sharp" in style or "square" in style:
        return 4
    return 12


def _is_dark(hex_color: str) -> bool:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    if not m:
        return False
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def _esc(s: str) -> str:
    return _html.escape(str(s), quote=True)


# --------------------------------------------------------------------------- #
# Branded inline-SVG icon system (NO photos): clean stroke icons that inherit the
# palette accent, so every page reads on-brand + custom, never AI-stock-photo.
# --------------------------------------------------------------------------- #
_ICON_PATHS: dict[str, str] = {
    "bolt": '<polygon points="13 2 4 14 11 14 9 22 20 10 13 10"/>',
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "cpu": ('<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
            '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    "link": ('<path d="M9 15l6-6"/><path d="M11 6l1-1a4 4 0 0 1 6 6l-1 1"/>'
             '<path d="M13 18l-1 1a4 4 0 0 1-6-6l1-1"/>'),
    "gear": ('<circle cx="12" cy="12" r="3.2"/>'
             '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>'),
    "shield": '<path d="M12 2l8 4v5c0 5-4 9-8 11-4-2-8-6-8-11V6z"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "rocket": ('<path d="M5 15c-2 1-3 5-3 5s4-1 5-3"/>'
               '<path d="M9 15l-3-3c1-6 5-9 12-10-1 7-4 11-10 12z"/><circle cx="14.5" cy="9.5" r="1.6"/>'),
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M16 15c2 0 5 2 5 5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "puzzle": ('<path d="M10 4h4v3a2 2 0 1 0 4 0h2v4h-3a2 2 0 1 0 0 4h3v4h-4v-3a2 2 0 1 0-4 0v3H6v-4h3'
               'a2 2 0 1 0 0-4H6V7h4z"/>'),
    "sparkles": ('<path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9z"/>'
                 '<path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18z"/>'),
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
}
_ICON_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("audit", "research", "find", "analy", "assess", "discover"), "search"),
    (("automat", "workflow", "process", "engine", "run"), "gear"),
    (("agent", " ai", "bot", "autonom", "intellig", "smart"), "cpu"),
    (("integrat", "connect", "link", "stack", "api", "sync", "tool"), "link"),
    (("fast", "speed", "quick", "instant", "rapid", "week", "hour"), "bolt"),
    (("secure", "safe", "privacy", "data", "protect", "trust", "complian"), "shield"),
    (("grow", "scale", "result", "roi", "revenue", "perform", "metric", "proven"), "chart"),
    (("global", "world", "market", "continent", "region", "everywhere"), "globe"),
    (("ship", "launch", "deploy", "live", "product", "go-live"), "rocket"),
    (("support", "team", "people", "customer", "client", "human", "staff"), "users"),
    (("always", "24", "monitor", "uptime", "time"), "clock"),
    (("solution", "piece", "fit", "custom", "modular", "built"), "puzzle"),
)
_ICON_CYCLE: tuple[str, ...] = (
    "bolt", "cpu", "link", "chart", "gear", "shield", "globe", "rocket", "users", "puzzle", "layers", "sparkles",
)


def _pick_icon(text: str, index: int) -> str:
    low = f" {text.lower()} "
    for kws, name in _ICON_KEYWORDS:
        if any(k in low for k in kws):
            return name
    return _ICON_CYCLE[index % len(_ICON_CYCLE)]


def _icon_svg(name: str, cls: str = "ic") -> str:
    path = _ICON_PATHS.get(name, _ICON_PATHS["check"])
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{path}</svg>"
    )


def _hero_visual(heading: str) -> str:
    """A branded, photo-free hero visual: an accent-tinted panel with a large glyph and a
    small cluster of feature icons - reads custom + on-brand, no stock photo."""
    big = _icon_svg(_pick_icon(heading, 0), "ic-xl")
    chips = "".join(
        f'<span class="hchip">{_icon_svg(n, "ic-sm")}</span>'
        for n in (_ICON_CYCLE[1], _ICON_CYCLE[3], _ICON_CYCLE[5], _ICON_CYCLE[8])
    )
    return f'<div class="hero-visual"><div class="brandpanel"><div class="glyph">{big}</div><div class="hchips">{chips}</div></div></div>'


def _feature_row() -> str:
    """A row of branded icon chips for a centered hero (replaces a hero photo)."""
    labels = (("bolt", "Fast"), ("cpu", "Autonomous"), ("link", "Integrated"), ("shield", "Secure"))
    chips = "".join(
        f'<div class="frow-item">{_icon_svg(n, "ic-md")}<span>{_esc(lbl)}</span></div>'
        for n, lbl in labels
    )
    return f'<div class="feature-row">{chips}</div>'


def model_to_html(model: PageModel, *, fragment: bool = False) -> str:
    """Render the page model to premium, self-contained HTML. ``fragment=True`` returns
    just the ``<style>`` + ``<main>`` body (for embedding in the dashboard preview iframe
    or the WordPress body); otherwise a full standalone document."""
    pal = _palette(model.design)
    head_font, body_font = _fonts(model.design)
    radius = _radius(model.design)
    dark = _is_dark(pal["background"])
    parts = [_section_html(s, pal) for s in model.sections if s.visible]
    css = _CSS_TEMPLATE.format(
        bg=pal["background"], text=pal["text"], head=pal["primary"], accent=pal["accent"],
        muted=pal["secondary"], radius=radius, head_font=head_font, body_font=body_font,
        alt=_mix(pal["background"], dark), line=_line(pal, dark),
        card=_card_bg(pal["background"], dark), on_accent=("#04141b" if _is_dark(pal["accent"]) is False and dark else "#ffffff"),
        accent_soft=_soft(pal["accent"]), shadow=("0 24px 60px -22px rgba(0,0,0,.5)" if dark else "0 24px 60px -22px rgba(15,23,42,.22)"),
        cta_fg=("#04141b" if not _is_dark(pal["accent"]) else "#ffffff"),
    )
    body = f'<style>{css}</style>\n<main class="aios-doc">\n' + "\n".join(parts) + "\n</main>"
    if fragment:
        return body
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(model.title)}</title></head><body>{body}</body></html>"
    )


def _mix(bg: str, dark: bool) -> str:
    return "#0d1424" if dark else "#f6f8fb"


def _line(pal: dict[str, str], dark: bool) -> str:
    return "#1e2a44" if dark else "#e6ebf2"


def _card_bg(bg: str, dark: bool) -> str:
    return "#111a2e" if dark else "#ffffff"


def _soft(accent: str) -> str:
    return f"color-mix(in srgb, {accent} 14%, transparent)"


def _btn(label: str, url: str, cls: str) -> str:
    return f'<a class="{cls}" href="{_esc(url or "#")}">{_esc(label)}</a>'


def _photo(im: Image, cls: str) -> str:
    if not im.url:
        return ""
    return f'<div class="{cls}"><img src="{_esc(im.url)}" alt="{_esc(im.alt)}" loading="lazy"></div>'


def _section_html(s: Section, pal: dict[str, str]) -> str:
    d = s.data or {}
    cls = f"aios-sec aios-{re.sub(r'[^a-z0-9]+', '-', s.kind.lower())}"
    attrs = f'data-aios-id="{_esc(s.id)}" data-aios-kind="{_esc(s.kind)}"'
    has_photo = bool(s.images and s.images[0].url)
    if s.kind == "hero":
        split = "split" in (s.layout or "")
        buttons = "".join(
            _btn(b.get("label", ""), b.get("url", ""), "btn btn-primary" if i == 0 else "btn btn-ghost")
            for i, b in enumerate(d.get("buttons") or [])
        )
        text = (
            f'<div class="hero-text"><h1 data-aios-field="heading">{_inline_html(s.heading)}</h1>'
            f'<p class="lede" data-aios-field="subhead">{_inline_html(str(d.get("subhead", "")))}</p>'
            f'<div class="hero-cta">{buttons}</div></div>'
        )
        if split:
            # Split hero: a LARGE photo (gpt-image) beside the copy; icon panel if no photo.
            visual = _photo(s.images[0], "hero-visual") if has_photo else _hero_visual(s.heading)
            return f'<section class="{cls} hero split" {attrs}><div class="wrap">{text}{visual}</div></section>'
        # Centered hero: copy centered, a big full-width photo below (or a branded icon row).
        below = _photo(s.images[0], "hero-visual wide") if has_photo else _feature_row()
        return f'<section class="{cls} hero centered" {attrs}><div class="wrap">{text}{below}</div></section>'
    if s.kind in GRID_KINDS:
        cards_data = d.get("cards") or []
        cards = "".join(
            f'<article class="card"><div class="card-ic">'
            f"{_icon_svg(_pick_icon(str(c.get('title', '')) + ' ' + str(c.get('desc', '')), i))}</div>"
            f'<h3 data-aios-field="cards.{i}.title">{_inline_html(c.get("title") or (c.get("desc") or "")[:40])}</h3>'
            f'<p data-aios-field="cards.{i}.desc">{_inline_html(c.get("desc") or "")}</p></article>'
            for i, c in enumerate(cards_data)
        )
        img = _photo(s.images[0], "band-visual") if has_photo else ""
        n = min(len(cards_data), 4) or 3
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>{img}'
                f'<div class="grid grid-{n}">{cards}</div></div></section>')
    if s.kind == "process":
        items = "".join(
            f'<li><span class="step-n">{i}</span><p data-aios-field="steps.{i-1}">{_inline_html(st)}</p></li>'
            for i, st in enumerate(d.get("steps") or [], start=1)
        )
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<ol class="steps">{items}</ol></div></section>')
    if s.kind == "faq":
        items = "".join(
            f'<details><summary><span data-aios-field="faq.{i}.q">{_inline_html(f.get("q", ""))}</span>'
            f'<span class="chev">+</span></summary><div class="ans">'
            f'<p data-aios-field="faq.{i}.a">{_inline_html(f.get("a", ""))}</p></div></details>'
            for i, f in enumerate(d.get("faq") or [])
        )
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap narrow">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="faq">{items}</div></div></section>')
    if s.kind == "testimonials":
        cards = "".join(
            f'<figure class="quote"><blockquote data-aios-field="quotes.{i}">{_inline_html(q)}</blockquote></figure>'
            for i, q in enumerate(d.get("quotes") or [])
        )
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="grid grid-3">{cards}</div></div></section>')
    if s.kind == "cta":
        btn = d.get("button") or {}
        return (f'<section class="{cls} cta" {attrs}><div class="wrap">'
                f'<h2 data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<p data-aios-field="text">{_inline_html(str(d.get("text", "")))}</p>'
                f'{_btn(str(btn.get("label", "Get in touch")), str(btn.get("url", "#")), "btn btn-invert")}'
                f"</div></section>")
    # prose / proof / other
    img = _photo(s.images[0], "prose-visual") if has_photo else ""
    heading = f'<h2 class="sec-h left" data-aios-field="heading">{_inline_html(s.heading)}</h2>' if s.heading else ""
    inner = f'<div class="prose-text">{heading}<div data-aios-field="html">{d.get("html", "")}</div></div>{img}'
    wrap_cls = "wrap prose-split" if img else "wrap narrow"
    return f'<section class="{cls} band" {attrs}><div class="{wrap_cls}">{inner}</div></section>'


_CSS_TEMPLATE = (
    "*{{box-sizing:border-box}}.aios-doc{{margin:0;color:{text};background:{bg};"
    "font-family:{body_font};line-height:1.6;font-size:17px;-webkit-font-smoothing:antialiased}}"
    ".aios-doc img{{max-width:100%;display:block}}"
    ".aios-doc .wrap{{max-width:1160px;margin:0 auto;padding:0 28px}}.aios-doc .wrap.narrow{{max-width:820px}}"
    ".aios-doc h1,.aios-doc h2,.aios-doc h3{{font-family:{head_font};color:{head};font-weight:800;letter-spacing:-.02em;line-height:1.1}}"
    ".aios-doc a{{color:{accent};text-decoration:none}}"
    ".aios-doc .btn{{display:inline-block;padding:14px 26px;border-radius:{radius}px;font-weight:600;font-size:15px;border:2px solid transparent}}"
    ".aios-doc .btn-primary{{background:{accent};color:{on_accent}}}"
    ".aios-doc .btn-ghost{{background:transparent;color:{text};border-color:{line}}}"
    ".aios-doc .btn-invert{{background:{bg};color:{accent}}}"
    ".aios-doc .hero{{padding:76px 0 60px;border-bottom:1px solid {line}}}"
    ".aios-doc .hero .wrap{{display:grid;grid-template-columns:1fr 1.04fr;gap:56px;align-items:center}}"
    ".aios-doc .hero.centered .wrap{{grid-template-columns:1fr;text-align:center;max-width:1000px}}"
    ".aios-doc .hero h1{{font-size:56px;margin:.1em 0 .35em}}"
    ".aios-doc .hero .lede{{font-size:20px;color:{muted};margin:0}}.aios-doc .hero.centered .lede{{margin:0 auto;max-width:46ch}}"
    ".aios-doc .hero-cta{{display:flex;gap:14px;margin-top:28px;flex-wrap:wrap}}.aios-doc .hero.centered .hero-cta{{justify-content:center}}"
    ".aios-doc .hero-visual img{{border-radius:22px;box-shadow:{shadow};width:100%;min-height:440px;aspect-ratio:4/3;object-fit:cover}}"
    ".aios-doc .hero-visual.wide{{grid-column:1/-1;margin-top:38px}}.aios-doc .hero-visual.wide img{{aspect-ratio:21/9;min-height:0;max-height:520px}}"
    ".aios-doc .band{{padding:74px 0}}.aios-doc .band.alt{{background:{alt}}}"
    ".aios-doc .band-visual img,.aios-doc .prose-visual img{{border-radius:18px;box-shadow:{shadow};aspect-ratio:16/9;object-fit:cover;margin:0 auto 30px}}"
    ".aios-doc .sec-h{{font-size:38px;text-align:center;margin:0 0 42px}}.aios-doc .sec-h.left{{text-align:left;margin-bottom:18px}}"
    ".aios-doc .grid{{display:grid;gap:22px}}.aios-doc .grid-2{{grid-template-columns:repeat(2,1fr)}}"
    ".aios-doc .grid-3{{grid-template-columns:repeat(3,1fr)}}.aios-doc .grid-4{{grid-template-columns:repeat(4,1fr)}}"
    ".aios-doc .card{{background:{card};border:1px solid {line};border-radius:18px;padding:30px 26px;transition:transform .15s,box-shadow .15s,border-color .15s}}"
    ".aios-doc .card:hover{{transform:translateY(-3px);box-shadow:{shadow};border-color:{accent}}}"
    ".aios-doc .card-ic{{width:54px;height:54px;border-radius:14px;display:grid;place-items:center;background:{accent_soft};color:{accent};margin-bottom:18px}}"
    ".aios-doc .ic{{width:26px;height:26px}}"
    ".aios-doc .card h3{{margin:0 0 8px;font-size:20px}}.aios-doc .card p{{margin:0;color:{muted};font-size:15px}}"
    ".aios-doc .steps{{list-style:none;padding:0;max-width:820px;margin:0 auto;display:grid;gap:16px}}"
    ".aios-doc .steps li{{display:flex;gap:20px;align-items:flex-start;background:{card};border:1px solid {line};border-radius:16px;padding:20px 24px}}"
    ".aios-doc .step-n{{flex:0 0 auto;width:40px;height:40px;border-radius:50%;background:{accent};color:{on_accent};font-weight:800;display:grid;place-items:center}}"
    ".aios-doc .steps p{{margin:6px 0 0}}"
    ".aios-doc .quote{{margin:0;background:{card};border:1px solid {line};border-radius:18px;padding:26px}}"
    ".aios-doc .quote blockquote{{margin:0;font-size:17px;line-height:1.55}}"
    ".aios-doc .prose-split{{display:grid;grid-template-columns:1fr 1fr;gap:44px;align-items:center}}"
    ".aios-doc .prose-text p{{color:{muted};font-size:17px}}"
    ".aios-doc .faq details{{border:1px solid {line};border-radius:14px;margin-bottom:12px;background:{card};overflow:hidden}}"
    ".aios-doc .faq summary{{list-style:none;cursor:pointer;padding:20px 22px;font-weight:700;color:{head};font-size:17px;display:flex;justify-content:space-between}}"
    ".aios-doc .faq summary::-webkit-details-marker{{display:none}}.aios-doc .faq .chev{{color:{accent};font-size:22px}}"
    ".aios-doc .faq details[open] .chev{{transform:rotate(45deg)}}.aios-doc .faq .ans{{padding:0 22px 20px;color:{muted}}}.aios-doc .faq .ans p{{margin:0}}"
    ".aios-doc .cta{{background:{accent};color:{cta_fg};text-align:center;padding:80px 0}}"
    ".aios-doc .cta h2{{font-size:40px;margin:0 0 14px;color:{cta_fg}}}.aios-doc .cta p{{font-size:19px;opacity:.92;max-width:52ch;margin:0 auto 28px}}"
    ".aios-doc .brandpanel{{background:linear-gradient(160deg,{accent_soft},transparent);border:1px solid {line};"
    "border-radius:24px;padding:48px;min-height:400px;display:flex;flex-direction:column;justify-content:center;"
    "align-items:center;gap:30px}}"
    ".aios-doc .glyph{{color:{accent}}}.aios-doc .ic-xl{{width:124px;height:124px}}"
    ".aios-doc .hchips{{display:flex;gap:14px}}.aios-doc .hchip{{width:54px;height:54px;border-radius:14px;"
    "background:{card};border:1px solid {line};display:grid;place-items:center;color:{accent}}}"
    ".aios-doc .ic-sm{{width:24px;height:24px}}"
    ".aios-doc .feature-row{{display:flex;gap:14px;justify-content:center;margin-top:38px;flex-wrap:wrap}}"
    ".aios-doc .frow-item{{display:flex;align-items:center;gap:10px;padding:12px 18px;border:1px solid {line};"
    "border-radius:999px;background:{card};color:{head};font-weight:600;font-size:15px}}"
    ".aios-doc .ic-md{{width:20px;height:20px;color:{accent}}}"
    "@media(max-width:860px){{.aios-doc .hero .wrap,.aios-doc .prose-split{{grid-template-columns:1fr}}"
    ".aios-doc .grid-3,.aios-doc .grid-4{{grid-template-columns:1fr 1fr}}.aios-doc .hero h1{{font-size:38px}}"
    ".aios-doc .hero-visual img{{min-height:300px}}}}"
)
