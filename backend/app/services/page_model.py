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


#: Generic families a font stack can END with. A stack that names none of these is
#: incomplete: when every family in it is missing, the browser falls back to its default,
#: which is a SERIF on every major engine.
_GENERIC_FAMILIES = ("serif", "sans-serif", "monospace", "cursive", "fantasy",
                     "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace")

#: What gets appended to an analyzed stack that ends nowhere.
_FALLBACK_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'


def _complete_stack(stack: str) -> str:
    """A font stack that is guaranteed to land somewhere sensible.

    MEASURED ON A REAL CAPTURE. The analyzer read hudamoji.pk and returned
    ``Inter, "Inter Fallback"`` - which is what the site's own CSS says, and is correct as
    a transcription. It is also a stack naming two families that exist on that site's
    visitors' machines only if Inter is installed, and ending in no generic family at all.
    On a machine without Inter, every published page rendered in the browser's default
    serif: a sans-serif design system, transcribed faithfully, published as Times.

    So a generic fallback is appended unless the stack already ends in one. The analyzed
    families keep their priority - this only decides where the chain STOPS.
    """
    stack = stack.strip().rstrip(",").strip()
    if not stack:
        return _FALLBACK_STACK
    families = [f.strip().strip('"\'').lower() for f in stack.split(",")]
    if any(f in _GENERIC_FAMILIES for f in families):
        return stack
    return f"{stack}, {_FALLBACK_STACK}"


def _fonts(design: dict[str, Any]) -> tuple[str, str]:
    t = _as_dict(design.get("typography"))
    head = _complete_stack(str(t.get("heading_font") or "Sora, system-ui, sans-serif"))
    body = _complete_stack(str(t.get("body_font") or "Inter, system-ui, sans-serif"))
    return head, body


#: Families never worth asking a font host for: they are the browser's own, or they are
#: the generic families `_complete_stack` appends.
_SYSTEM_FAMILIES: frozenset[str] = frozenset({
    *_GENERIC_FAMILIES,
    "-apple-system", "blinkmacsystemfont", "segoe ui", "roboto", "helvetica",
    "helvetica neue", "arial", "times", "times new roman", "georgia", "courier",
    "courier new", "verdana", "tahoma", "inherit", "initial", "unset",
})

#: Suffixes a BUILD TOOL appends to a family name, never a real typeface.
#:
#: MEASURED on a live capture: a Next.js site's computed CSS reads
#: `Inter, "Inter Fallback"` - the second entry is a locally-generated metric-matched
#: face that exists only in that site's build. Asking a font host for it is asking for a
#: family nobody has, and the analyzer is right to transcribe it: what is wrong is
#: treating it as something to go and fetch.
_BUILD_ARTEFACT_SUFFIXES: tuple[str, ...] = ("fallback", "local", "override", "adjusted")


def font_families(design: dict[str, Any]) -> list[str]:
    """The REAL typeface names this design asks for, in priority order.

    WHY THE PUBLISH PATH NEEDS THIS. ``model_css`` writes the analyzed font stack into the
    page, and naming a family is not the same as having it: on a site that never loaded
    Poppins, ``font-family: Poppins, …`` renders in whatever comes next in the stack. The
    page then looks nothing like the design it was built from, and nothing reports a
    problem because the CSS is exactly right. So the families travel with the payload and
    the publisher plugin loads them.

    System and generic families are dropped - they need no loading and asking a font host
    for "sans-serif" is a 404 the page waits on.
    """
    out: list[str] = []
    for stack in _fonts(design):
        for raw in stack.split(","):
            name = raw.strip().strip("\"'")
            lowered = name.lower()
            if not name or lowered in _SYSTEM_FAMILIES:
                continue
            if lowered.split()[-1] in _BUILD_ARTEFACT_SUFFIXES and " " in lowered:
                continue
            if name not in out:
                out.append(name)
    return out


def _radius(design: dict[str, Any]) -> int:
    style = str(_as_dict(design.get("components")).get("button_style") or "").lower()
    if "pill" in style:
        return 999
    if "sharp" in style or "square" in style:
        return 4
    return 12


#: A few colour keywords worth knowing, because a real stylesheet uses them and an
#: unparsed colour is silently treated as LIGHT, which is the dangerous direction.
_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "transparent": (255, 255, 255),
    "navy": (0, 0, 128), "maroon": (128, 0, 0), "darkblue": (0, 0, 139),
    "midnightblue": (25, 25, 112), "darkslategray": (47, 79, 79), "dimgray": (105, 105, 105),
}


def _rgb(color: str) -> tuple[int, int, int] | None:
    """Parse a CSS colour to ``(r, g, b)``, or ``None`` when it cannot be read.

    ACCEPTS WHAT A REAL CAPTURE PRODUCES, not just what this module used to emit. The
    analyzer reads computed styles out of a live browser, and a browser reports colours as
    ``rgb(23, 23, 23)`` - never as a hex triplet. Parsing only ``#rrggbb`` meant every
    analyzed palette was unreadable here, and "unreadable" resolved to "light": a client
    whose accent was near-black got a call-to-action band painted in it with near-black
    text on top. The band published invisible.
    """
    value = color.strip().lower()
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    m = re.fullmatch(r"#?([0-9a-f]{6})", value)
    if m:
        return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.fullmatch(r"#?([0-9a-f]{3})", value)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1))  # type: ignore[return-value]
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*(?:[,/].*)?\)", value)
    if m:
        try:
            return tuple(max(0, min(255, round(float(m.group(i))))) for i in (1, 2, 3))  # type: ignore[return-value]
        except ValueError:
            return None
    return None


def _is_dark(hex_color: str) -> bool:
    """Whether text on this colour needs to be light. Unparseable -> treated as light."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return False
    r, g, b = rgb
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


def model_css(model: PageModel) -> str:
    """The page's stylesheet as RAW CSS text - no ``<style>`` wrapper.

    SEPARATE FROM THE BODY ON PURPOSE. WordPress will not accept a stylesheet inside a
    post: the AIOS Publisher plugin strips ``<style>`` blocks including their contents
    before saving, and it has to - ``wp_kses_post`` removes the tag but KEEPS the text,
    which would dump the whole stylesheet onto the page as visible characters. A page
    published with its design inline therefore arrives with every class name intact and
    not one rule behind them, which is exactly how a carefully composed page renders as a
    stack of naked paragraphs.

    So the publish path sends this text in the payload's ``design_css`` field, which the
    plugin sanitises and enqueues in ``<head>``, and sends the body separately. Every rule
    is derived from ``model.design`` - the analyzed site's own palette, fonts and radius -
    so the SAME analysis that chose the design tokens is what styles the published page.
    """
    pal = _palette(model.design)
    head_font, body_font = _fonts(model.design)
    dark = _is_dark(pal["background"])
    # TEXT ON THE ACCENT depends on the ACCENT and on nothing else. Both of these used to
    # also consult the page background, which made them wrong in two of the four
    # combinations: a light accent on a light page got white text (a yellow button with
    # white words on it), and a dark accent read as unparseable got dark text on a dark
    # band. One rule, applied to one colour, is correct everywhere.
    on_accent = "#ffffff" if _is_dark(pal["accent"]) else "#04141b"
    return _CSS_TEMPLATE.format(
        bg=pal["background"], text=pal["text"], head=pal["primary"], accent=pal["accent"],
        muted=pal["secondary"], radius=_radius(model.design),
        head_font=head_font, body_font=body_font,
        alt=_mix(pal["background"], dark), line=_line(pal, dark),
        card=_card_bg(pal["background"], dark), on_accent=on_accent,
        accent_soft=_soft(pal["accent"]), shadow=("0 24px 60px -22px rgba(0,0,0,.5)" if dark else "0 24px 60px -22px rgba(15,23,42,.22)"),
        cta_fg=on_accent,
    )


def model_body_html(model: PageModel) -> str:
    """The rendered ``<main class="aios-doc">`` body ALONE - no ``<style>`` block.

    The half of :func:`model_to_html` that survives a WordPress publish; pair it with
    :func:`model_css` (see that docstring for why the two have to travel separately)."""
    pal = _palette(model.design)
    parts = [_section_html(s, pal) for s in model.sections if s.visible]
    return '<main class="aios-doc">\n' + "\n".join(parts) + "\n</main>"


def model_to_html(model: PageModel, *, fragment: bool = False) -> str:
    """Render the page model to premium, self-contained HTML. ``fragment=True`` returns
    just the ``<style>`` + ``<main>`` body (for embedding in the dashboard preview iframe
    or the WordPress body); otherwise a full standalone document."""
    body = f'<style>{model_css(model)}</style>\n{model_body_html(model)}'
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


def _columns(count: int) -> int:
    """How many columns a grid of ``count`` cards should use.

    THE RULE IS FEWEST ORPHANS, not "as many as will fit". Taking `min(count, 4)` looks
    right until the count is five: four across and one alone on the next row, which reads
    as a layout accident rather than as five things. MEASURED on a generated About page -
    the writer returned five benefits and the page published 4 + 1.

    Five is better as 3 + 2, seven as 4 + 3. Wider wins a tie, because a page of cards
    reads better wide; and a single card gets its own centred width rather than stretching
    across the full container.
    """
    if count <= 1:
        return 1
    if count <= 4:
        return count
    # Among 2, 3 and 4 columns, take the one whose last row is fullest; ties go wide.
    return max((3, 2, 4), key=lambda c: ((count % c) or c, c))


def _photo(im: Image, cls: str) -> str:
    if not im.url:
        return ""
    return (
        f'<div class="{cls}"><img src="{_esc(im.url)}" alt="{_esc(im.alt)}" '
        f'title="{_esc(im.alt)}" loading="lazy"></div>'
    )


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
        points = "".join(
            f'<li data-aios-field="bullets.{i}">'
            f'{_inline_html(str(b.get("text") if isinstance(b, dict) else b))}</li>'
            for i, b in enumerate(d.get("bullets") or [])
        )
        bullets = f'<ul class="hero-points">{points}</ul>' if points else ""
        text = (
            f'<div class="hero-text"><h1 data-aios-field="heading">{_inline_html(s.heading)}</h1>'
            f'<p class="lede" data-aios-field="subhead">{_inline_html(str(d.get("subhead", "")))}</p>'
            f'{bullets}<div class="hero-cta">{buttons}</div></div>'
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
        n = _columns(len(cards_data))
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>{img}'
                f'<div class="grid grid-{n}">{cards}</div></div></section>')
    if s.kind == "process":
        # A step is EITHER a plain string (the legacy prose-derived shape) or a
        # {title, text} pair (what the composer returns). Both render; the pair renders
        # as a real step - a name you can scan and a sentence that says what happens in
        # it - which is the difference between a process section and a numbered list.
        steps_html: list[str] = []
        for i, st in enumerate(d.get("steps") or [], start=1):
            if isinstance(st, dict):
                title = _inline_html(str(st.get("title", "")))
                text = _inline_html(str(st.get("text", "")))
                inner = (
                    f'<div class="step-b"><h3 data-aios-field="steps.{i-1}.title">{title}</h3>'
                    f'<p data-aios-field="steps.{i-1}.text">{text}</p></div>'
                )
            else:
                inner = f'<div class="step-b"><p data-aios-field="steps.{i-1}">{_inline_html(str(st))}</p></div>'
            steps_html.append(f'<li><span class="step-n">{i}</span>{inner}</li>')
        intro = (
            f'<p class="sec-sub" data-aios-field="intro">{_inline_html(str(d.get("intro", "")))}</p>'
            if d.get("intro") else ""
        )
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>{intro}'
                f'<ol class="steps">{"".join(steps_html)}</ol></div></section>')
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
    if s.kind in ("testimonials", "reviews"):
        # ONE RENDERER FOR BOTH. A service page calls them testimonials and a location
        # page calls them reviews; both are quotes the client supplied, and the only
        # difference is the heading above them. Drawing `reviews` here rather than letting
        # it fall through to the prose renderer is what stopped a location page publishing
        # a "Customer reviews" heading with blank space under it.
        #
        # ATTRIBUTION IS PART OF THE QUOTE. An unattributed testimonial is a sentence in
        # quote marks, and a reader discounts it accordingly - so when the client supplied
        # a name and a role, they render. When they did not, the quote stands alone rather
        # than inventing a "- Satisfied Customer".
        quote_cards: list[str] = []
        for i, q in enumerate(d.get("quotes") or []):
            if isinstance(q, dict):
                quote, author, role = (
                    str(q.get("quote", "")), str(q.get("author", "")), str(q.get("role", ""))
                )
            else:
                quote, author, role = str(q), "", ""
            who = ", ".join(x for x in (author, role) if x.strip())
            cite = f'<figcaption data-aios-field="quotes.{i}.author">{_inline_html(who)}</figcaption>' if who else ""
            quote_cards.append(
                f'<figure class="quote"><blockquote data-aios-field="quotes.{i}">'
                f"{_inline_html(quote)}</blockquote>{cite}</figure>"
            )
        n = _columns(len(quote_cards))
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="grid grid-{n}">{"".join(quote_cards)}</div></div></section>')

    if s.kind == "pricing":
        tiers = d.get("tiers") or []
        tier_cards: list[str] = []
        for i, t in enumerate(tiers):
            if not isinstance(t, dict):
                continue
            feats = "".join(
                f"<li>{_inline_html(str(f))}</li>" for f in (t.get("features") or [])
            )
            feats_html = f'<ul class="tier-f">{feats}</ul>' if feats else ""
            cta_label = str(t.get("cta_label") or "").strip()
            button = _btn(cta_label, "#contact", "btn btn-primary sm") if cta_label else ""
            tier_cards.append(
                f'<article class="tier"><h3 data-aios-field="tiers.{i}.name">'
                f'{_inline_html(str(t.get("name", "")))}</h3>'
                f'<div class="tier-price" data-aios-field="tiers.{i}.price">'
                f'{_inline_html(str(t.get("price", "")))}</div>'
                f'<p data-aios-field="tiers.{i}.summary">{_inline_html(str(t.get("summary", "")))}</p>'
                f"{feats_html}{button}</article>"
            )
        n = _columns(len(tier_cards))
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="grid grid-{n} tiers">{"".join(tier_cards)}</div></div></section>')

    if s.kind == "stats":
        tiles = "".join(
            f'<div class="stat"><span class="stat-v" data-aios-field="stats.{i}.value">'
            f'{_inline_html(str(x.get("value", "")))}</span>'
            f'<span class="stat-l" data-aios-field="stats.{i}.label">'
            f'{_inline_html(str(x.get("label", "")))}</span></div>'
            for i, x in enumerate(d.get("stats") or []) if isinstance(x, dict)
        )
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="stats">{tiles}</div></div></section>')

    if s.kind == "team":
        people_cards = "".join(
            f'<article class="card person"><h3 data-aios-field="people.{i}.name">'
            f'{_inline_html(str(p.get("name", "")))}</h3>'
            f'<div class="role" data-aios-field="people.{i}.role">'
            f'{_inline_html(str(p.get("role", "")))}</div>'
            f'<p data-aios-field="people.{i}.bio">{_inline_html(str(p.get("bio", "")))}</p></article>'
            for i, p in enumerate(d.get("people") or []) if isinstance(p, dict)
        )
        n = _columns(len(d.get("people") or []))
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="grid grid-{n}">{people_cards}</div></div></section>')

    if s.kind == "service_areas":
        chips = "".join(
            f'<span class="area">{_inline_html(str(a.get("name") if isinstance(a, dict) else a))}</span>'
            for a in (d.get("areas") or [])
        )
        intro = (
            f'<p class="sec-sub" data-aios-field="intro">{_inline_html(str(d.get("intro", "")))}</p>'
            if d.get("intro") else ""
        )
        return (f'<section class="{cls} band" {attrs}><div class="wrap">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>{intro}'
                f'<div class="areas">{chips}</div></div></section>')

    if s.kind == "contact":
        # THE BUSINESS'S REAL DETAILS, each line present only when the client gave it.
        # A contact block that prints an empty "Phone:" label is worse than one that
        # simply does not mention a phone - it reads as a page that lost its data.
        rows = "".join(
            f'<div class="nap-row"><span class="nap-k">{label}</span>'
            f'<span class="nap-v" data-aios-field="{key}">{_inline_html(str(d[key]))}</span></div>'
            for key, label in (
                ("address", "Address"), ("phone", "Phone"),
                ("email", "Email"), ("hours", "Hours"),
            )
            if str(d.get(key) or "").strip()
        )
        if not rows:
            return ""
        name = (
            f'<p class="nap-name" data-aios-field="name">{_inline_html(str(d.get("name", "")))}</p>'
            if d.get("name") else ""
        )
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap narrow">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<div class="nap">{name}{rows}</div></div></section>')
    if s.kind == "related":
        items = "".join(
            f'<li><a href="{_esc(str(x.get("url", "")))}" '
            f'data-aios-field="links.{i}">{_inline_html(str(x.get("label", "")))}</a></li>'
            for i, x in enumerate(d.get("links") or []) if isinstance(x, dict)
        )
        if not items:
            return ""
        return (f'<section class="{cls} band" {attrs}><div class="wrap narrow">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<ul class="related">{items}</ul></div></section>')
    if s.kind == "proof" and d.get("points"):
        rows = "".join(
            f'<li><p class="claim" data-aios-field="points.{i}.claim">'
            f'{_inline_html(str(p.get("claim", "")))}</p>'
            f'<span class="src" data-aios-field="points.{i}.source">'
            f'{_inline_html(str(p.get("source", "")))}</span></li>'
            for i, p in enumerate(d.get("points") or []) if isinstance(p, dict)
        )
        return (f'<section class="{cls} band alt" {attrs}><div class="wrap narrow">'
                f'<h2 class="sec-h" data-aios-field="heading">{_inline_html(s.heading)}</h2>'
                f'<ul class="proof">{rows}</ul></div></section>')
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
    # NOTHING MAY PUSH THE PAGE WIDER THAN THE SCREEN. A generated page is published to
    # somebody else's theme and read mostly on a phone; a single unshrinkable child - a
    # long unbroken word, a grid that did not collapse, an image without a max-width -
    # makes the whole document scroll sideways, and every heading gets cut off at the
    # right edge. MEASURED at 390px after a specificity mistake left the hero at two
    # columns: the text was clipped mid-word down the entire page.
    "*{{box-sizing:border-box}}"
    ".aios-doc{{overflow-x:hidden;max-width:100%;margin:0;color:{text};background:{bg};"
    "font-family:{body_font};line-height:1.6;font-size:17px;-webkit-font-smoothing:antialiased}}"
    ".aios-doc img{{max-width:100%;display:block}}"
    ".aios-doc .wrap{{max-width:1160px;margin:0 auto;padding:0 28px}}.aios-doc .wrap.narrow{{max-width:820px}}"
    ".aios-doc h1,.aios-doc h2,.aios-doc h3{{font-family:{head_font};color:{head};font-weight:800;letter-spacing:-.02em;line-height:1.1}}"
    # THE TYPEFACE, RESTATED ON THE ELEMENTS THEMSELVES.
    #
    # `.aios-doc {{font-family}}` alone sets the family once and lets it inherit, which is
    # correct CSS and not enough on somebody else's WordPress: a theme that styles its
    # text elements DIRECTLY (`h2 {{font-family:...}}`, `.entry-content p {{...}}`) beats an
    # inherited value, because inheritance loses to any rule that matches the element.
    # MEASURED on a live site whose theme sets its own font on every heading - the page
    # published carrying the client's design system and rendered in the theme's typeface.
    #
    # Restating it at `.aios-doc <element>` (0,1,1) outranks a bare element selector and a
    # single-class one, so the design wins on a normal theme. A theme using `!important`
    # still wins, and that is the correct place to stop: overriding an author's explicit
    # !important would make OUR page the one nobody can restyle.
    ".aios-doc h4,.aios-doc h5,.aios-doc h6{{font-family:{head_font}}}"
    ".aios-doc p,.aios-doc li,.aios-doc a,.aios-doc span,.aios-doc div,"
    ".aios-doc figcaption,.aios-doc blockquote,.aios-doc summary,.aios-doc details,"
    ".aios-doc strong,.aios-doc em,.aios-doc button{{font-family:{body_font}}}"
    ".aios-doc a{{color:{accent};text-decoration:none}}"
    ".aios-doc .btn{{display:inline-block;padding:14px 26px;border-radius:{radius}px;font-weight:600;font-size:15px;border:2px solid transparent}}"
    ".aios-doc .btn-primary{{background:{accent};color:{on_accent}}}"
    ".aios-doc .btn-ghost{{background:transparent;color:{text};border-color:{line}}}"
    ".aios-doc .btn-invert{{background:{bg};color:{accent}}}"
    ".aios-doc .hero{{padding:76px 0 60px;border-bottom:1px solid {line}}}"
    ".aios-doc .hero .wrap{{display:grid;gap:56px;align-items:center}}"
    # THE SPLIT HERO'S COLUMNS, NAMED. This used to be the unnamed default on
    # `.hero .wrap`, with `.centered` as the only modifier - so the markup carried a
    # `split` class that matched no rule at all. A class nobody can find the rule for is
    # a class the next person deletes, and the hero silently becomes one column.
    ".aios-doc .hero.split .wrap{{grid-template-columns:1fr 1.04fr}}"
    ".aios-doc .hero.centered .wrap{{grid-template-columns:1fr;text-align:center;max-width:1000px}}"
    ".aios-doc .hero h1{{font-size:clamp(34px,3.4vw,52px);margin:.1em 0 .35em;text-wrap:balance}}"
    ".aios-doc .hero .lede{{font-size:20px;color:{muted};margin:0}}.aios-doc .hero.centered .lede{{margin:0 auto;max-width:46ch}}"
    ".aios-doc .hero-cta{{display:flex;gap:14px;margin-top:28px;flex-wrap:wrap}}.aios-doc .hero.centered .hero-cta{{justify-content:center}}"
    ".aios-doc .hero-visual img{{border-radius:22px;box-shadow:{shadow};width:100%;min-height:440px;aspect-ratio:4/3;object-fit:cover}}"
    ".aios-doc .hero-visual.wide{{grid-column:1/-1;margin-top:38px}}.aios-doc .hero-visual.wide img{{aspect-ratio:21/9;min-height:0;max-height:520px}}"
    ".aios-doc .band{{padding:74px 0}}.aios-doc .band.alt{{background:{alt}}}"
    ".aios-doc .band-visual img,.aios-doc .prose-visual img{{border-radius:18px;box-shadow:{shadow};aspect-ratio:16/9;object-fit:cover;margin:0 auto 30px}}"
    ".aios-doc .sec-h{{font-size:38px;text-align:center;margin:0 0 42px}}.aios-doc .sec-h.left{{text-align:left;margin-bottom:18px}}"
    ".aios-doc .grid{{display:grid;gap:22px}}.aios-doc .grid-2{{grid-template-columns:repeat(2,1fr)}}"
    # A grid of ONE. The card count is measured from the data, so a client who supplied a
    # single price tier or a single testimonial gets `grid-1` - and without a rule that
    # lone card stretched the full 1160px content width, which reads as a layout accident
    # rather than as one plan. Centered at a card's natural width instead.
    ".aios-doc .grid-1{{grid-template-columns:minmax(0,440px);justify-content:center}}"
    # The hero's copy column. `min-width:0` is not cosmetic: a grid item's default
    # `min-width:auto` refuses to shrink below its longest unbreakable word, so one long
    # headline word or URL pushed the hero photo off the right edge of the page.
    ".aios-doc .hero-text{{min-width:0}}"
    # Wide enough for a headline, not the full 1160px. `ch` here is measured against the
    # container's BODY size, not the h1's, so a value picked to read well for a paragraph
    # squeezes a 52px headline into three ragged lines - which is what 44ch did.
    ".aios-doc .hero.centered .hero-text{{max-width:880px;margin:0 auto}}"
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
    ".aios-doc .step-b h3{{margin:0 0 4px;font-size:18px}}.aios-doc .step-b p{{margin:0;color:{muted};font-size:15px}}"
    ".aios-doc .sec-sub{{text-align:center;color:{muted};font-size:17px;max-width:62ch;margin:-28px auto 36px}}"
    ".aios-doc .quote{{margin:0;background:{card};border:1px solid {line};border-radius:18px;padding:26px;"
    "display:flex;flex-direction:column;gap:14px}}"
    ".aios-doc .quote blockquote{{margin:0;font-size:17px;line-height:1.55}}"
    ".aios-doc .quote figcaption{{color:{muted};font-size:14px;font-weight:600;margin-top:auto}}"
    # --- pricing tiers: the card the eye compares across, so the price is the biggest
    # thing in it and every card is the same height.
    ".aios-doc .tiers .tier{{background:{card};border:1px solid {line};border-radius:18px;padding:30px 26px;"
    "display:flex;flex-direction:column;gap:12px}}"
    ".aios-doc .tier h3{{margin:0;font-size:20px}}"
    ".aios-doc .tier-price{{font-family:{head_font};font-size:38px;font-weight:800;color:{accent};line-height:1}}"
    ".aios-doc .tier p{{margin:0;color:{muted};font-size:15px}}"
    ".aios-doc .tier-f{{list-style:none;padding:0;margin:6px 0 0;display:grid;gap:8px;font-size:15px;color:{muted}}}"
    ".aios-doc .tier-f li{{padding-left:22px;position:relative}}"
    ".aios-doc .tier-f li:before{{content:'';position:absolute;left:0;top:7px;width:12px;height:7px;"
    "border-left:2px solid {accent};border-bottom:2px solid {accent};transform:rotate(-45deg)}}"
    ".aios-doc .btn.sm{{padding:10px 18px;font-size:14px;margin-top:auto;text-align:center}}"
    # --- stat tiles + team + areas + proof
    ".aios-doc .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:22px}}"
    ".aios-doc .stat{{background:{card};border:1px solid {line};border-radius:18px;padding:28px 24px;text-align:center}}"
    ".aios-doc .stat-v{{display:block;font-family:{head_font};font-size:44px;font-weight:800;color:{accent};line-height:1}}"
    ".aios-doc .stat-l{{display:block;margin-top:8px;color:{muted};font-size:15px}}"
    ".aios-doc .person .role{{color:{accent};font-weight:600;font-size:14px;margin-bottom:8px}}"
    ".aios-doc .areas{{display:flex;flex-wrap:wrap;gap:10px;justify-content:center}}"
    ".aios-doc .area{{padding:10px 18px;border:1px solid {line};border-radius:999px;background:{card};"
    "font-size:15px;color:{head};font-weight:600}}"
    ".aios-doc .proof{{list-style:none;padding:0;margin:0;display:grid;gap:14px}}"
    ".aios-doc .proof li{{background:{card};border:1px solid {line};border-left:3px solid {accent};"
    "border-radius:14px;padding:18px 22px}}"
    ".aios-doc .proof .claim{{margin:0 0 6px;font-weight:600}}"
    ".aios-doc .proof .src{{color:{muted};font-size:14px}}"
    ".aios-doc .hero-points{{list-style:none;padding:0;margin:22px 0 0;display:grid;gap:10px}}"
    ".aios-doc .hero-points li{{display:flex;gap:10px;align-items:flex-start;color:{muted};font-size:16px}}"
    ".aios-doc .hero-points li:before{{content:'';flex:0 0 auto;margin-top:7px;width:12px;height:7px;"
    "border-left:2px solid {accent};border-bottom:2px solid {accent};transform:rotate(-45deg)}}"
    ".aios-doc .hero.centered .hero-points{{max-width:44ch;margin-left:auto;margin-right:auto;text-align:left}}"
    ".aios-doc .prose-split{{display:grid;grid-template-columns:1fr 1fr;gap:44px;align-items:center}}"
    ".aios-doc .prose-text p{{color:{muted};font-size:17px}}"
    ".aios-doc .faq details{{border:1px solid {line};border-radius:14px;margin-bottom:12px;background:{card};overflow:hidden}}"
    ".aios-doc .faq summary{{list-style:none;cursor:pointer;padding:20px 22px;font-weight:700;color:{head};font-size:17px;display:flex;justify-content:space-between}}"
    ".aios-doc .faq summary::-webkit-details-marker{{display:none}}.aios-doc .faq .chev{{color:{accent};font-size:22px}}"
    ".aios-doc .faq details[open] .chev{{transform:rotate(45deg)}}.aios-doc .faq .ans{{padding:0 22px 20px;color:{muted}}}.aios-doc .faq .ans p{{margin:0}}"
    ".aios-doc .nap{{max-width:560px;margin:0 auto;background:{card};border:1px solid {line};border-radius:18px;padding:28px 30px}}"
    ".aios-doc .nap-name{{margin:0 0 14px;font-weight:700;font-size:19px;font-family:{head_font}}}"
    ".aios-doc .nap-row{{display:flex;gap:16px;padding:10px 0;border-top:1px solid {line}}}"
    ".aios-doc .nap-row:first-of-type{{border-top:0}}"
    ".aios-doc .nap-k{{flex:0 0 90px;color:{muted};font-size:14px;font-weight:600}}"
    ".aios-doc .nap-v{{font-size:15px}}"
    ".aios-doc .related{{list-style:none;padding:0;margin:0;display:grid;gap:10px;max-width:640px;margin-inline:auto}}"
    ".aios-doc .related li{{background:{card};border:1px solid {line};border-radius:14px}}"
    ".aios-doc .related a{{display:block;padding:16px 20px;font-weight:600;font-size:16px}}"
    ".aios-doc .related a:hover{{border-color:{accent}}}"
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
    # TABLET. The hero and the split prose stop being two columns; the wide grids halve.
    "@media(max-width:860px){{.aios-doc .hero.split .wrap,.aios-doc .hero .wrap,"
    ".aios-doc .prose-split{{grid-template-columns:1fr}}"
    ".aios-doc .grid-3,.aios-doc .grid-4{{grid-template-columns:1fr 1fr}}.aios-doc .hero h1{{font-size:38px}}"
    ".aios-doc .hero-visual img{{min-height:300px}}}}"
    # PHONE, AND THIS BREAKPOINT WAS MISSING ENTIRELY.
    #
    # Below 860px everything collapsed to two columns and then STOPPED. On a 390px phone
    # that left every card grid, every price tier, every stat tile and every quote two
    # abreast at roughly 160px each - a column narrower than the words in it - and the
    # areas chips, the numbered steps and the contact rows at desktop proportions. More
    # than half of the traffic to a client's page arrives on that layout, and it is the
    # half nobody screenshots.
    #
    # One column for anything built out of cards, and the ornamental widths (the step
    # number, the NAP label column) stand down so the text gets the room.
    "@media(max-width:620px){{"
    ".aios-doc{{font-size:16px}}"
    ".aios-doc .wrap{{padding:0 20px}}"
    ".aios-doc .hero.split .wrap{{grid-template-columns:1fr}}"
    ".aios-doc .grid,.aios-doc .grid-1,.aios-doc .grid-2,.aios-doc .grid-3,.aios-doc .grid-4"
    "{{grid-template-columns:1fr}}"
    ".aios-doc .stats{{grid-template-columns:repeat(2,1fr)}}"
    ".aios-doc .hero{{padding:52px 0 44px}}"
    ".aios-doc .hero h1{{font-size:clamp(28px,7.5vw,34px)}}"
    ".aios-doc .hero .lede{{font-size:17px}}"
    ".aios-doc .hero-cta{{flex-direction:column;align-items:stretch}}"
    ".aios-doc .hero-cta .btn{{text-align:center}}"
    ".aios-doc .hero-visual img{{min-height:220px}}"
    ".aios-doc .band{{padding:52px 0}}"
    ".aios-doc .sec-h{{font-size:28px;margin-bottom:28px}}"
    ".aios-doc .sec-sub{{margin:-18px auto 26px;font-size:16px}}"
    ".aios-doc .card{{padding:24px 20px}}"
    ".aios-doc .steps li{{gap:14px;padding:18px 18px}}"
    ".aios-doc .step-n{{width:32px;height:32px;font-size:14px}}"
    ".aios-doc .cta{{padding:56px 0}}.aios-doc .cta h2{{font-size:28px}}"
    ".aios-doc .cta p{{font-size:17px}}"
    ".aios-doc .nap-row{{flex-direction:column;gap:2px}}"
    ".aios-doc .nap-k{{flex:none}}"
    ".aios-doc .tier-price{{font-size:30px}}"
    ".aios-doc .stat-n{{font-size:34px}}"
    "}}"
)
