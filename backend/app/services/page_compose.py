"""Composed slots -> the editable page model the renderers already draw.

THE JOIN BETWEEN THE TWO HALVES OF THE FIX. ``content_pipeline.compose`` asks the writer
for a typed payload per wireframe slot; ``page_model`` already knows how to draw a hero, an
icon grid, a numbered process, an accordion, a price table and a CTA banner in the client's
own palette and type. What was missing between them was the join: the old path turned the
writer's PROSE into sections by guessing from its H2s, so the grids had no cards, the
process had no steps, and every slot fell through to the prose branch - a wall of text
where a designed component should have been.

This module is that join, and it does exactly three things:

  1. MAPS EACH SLOT to the field names the renderer reads (``cards``, ``steps``, ``faq``,
     ``quotes``, ``tiers`` ...). One table, so a renderer and a schema can never disagree
     about whether the key is `desc` or `text`.
  2. PLACES THE IMAGES DELIBERATELY. The hero gets the hero image; the rest go to the
     sections that are actually improved by a picture, in page order, one each. The old
     path injected an image after every Nth ``<h2>``, which is why a real client page ended
     up with photographs scattered between paragraphs like, in the operator's words,
     something a child had thrown at the wall.
  3. DROPS EMPTY SECTIONS. A slot that came back unusable is not rendered as an empty
     band - it is not rendered at all. The page is shorter and correct rather than
     complete and broken.

Pure: no network, no DB, no provider. It takes data and returns a model.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.page_model import Image, PageModel, Section

#: slot kind -> (renderer data key, the item field names in renderer order).
#: The LEFT side is the composer's schema (``content_pipeline.slots``); the RIGHT side is
#: what ``page_model._section_html`` reads. Keeping the translation in one table is what
#: stops a renderer quietly drawing nothing because a key was spelled differently.
_ITEM_MAP: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    # kind:            (source field, renderer field, ((src_sub, dst_sub), ...))
    "features": ("items", "cards", (("title", "title"), ("text", "desc"))),
    "benefits": ("items", "cards", (("title", "title"), ("text", "desc"))),
    "services": ("items", "cards", (("title", "title"), ("text", "desc"))),
    "process": ("steps", "steps", (("title", "title"), ("text", "text"))),
    "faq": ("items", "faq", (("question", "q"), ("answer", "a"))),
    "testimonials": (
        "quotes", "quotes", (("quote", "quote"), ("author", "author"), ("role", "role")),
    ),
    # A "reviews" section on a location page and a "testimonials" section on a service
    # page are the same thing rendered under a different heading: quotes the client
    # supplied. Mapped to the same renderer fields so both draw attributed quote cards.
    # This was missing, so a local page's reviews slot reached the renderer with no
    # payload and published as a heading with nothing under it.
    "reviews": (
        "quotes", "quotes", (("quote", "quote"), ("author", "author"), ("role", "role")),
    ),
    "pricing": (
        "tiers", "tiers",
        (("name", "name"), ("price", "price"), ("summary", "summary"),
         ("cta_label", "cta_label")),
    ),
    "stats": ("stats", "stats", (("value", "value"), ("label", "label"))),
    "team": ("people", "people", (("name", "name"), ("role", "role"), ("bio", "bio"))),
    "proof": ("points", "points", (("claim", "claim"), ("source", "source"))),
    "service_areas": ("areas", "areas", (("name", "name"),)),
}

#: Sections a picture genuinely improves, in the order we would give one out.
#:
#: PROSE ONLY, and that is the second half of the image fix. A card GRID already has a
#: visual rhythm - four icons, four titles, four lines - and a full-width photograph above
#: it competes with the thing it is meant to introduce; rendered, it reads exactly like the
#: stock image somebody pasted in to fill space. A run of paragraphs has no rhythm of its
#: own and genuinely gains one. So the hero takes the lead image, prose takes the rest, and
#: a template with no prose slot (a service page is hero/grid/steps/accordion/price) gets
#: ONE strong image rather than five scattered ones - which is also five fewer images to
#: pay for.
_IMAGE_PREFERENCE: tuple[str, ...] = ("intro", "about", "body", "conclusion")

#: Kinds whose payload is prose the renderer draws as HTML.
_PROSE_KINDS: frozenset[str] = frozenset({"intro", "about", "conclusion"})


def _para_html(items: Any) -> str:
    """Paragraph items -> the ``<p>`` run the prose renderer expects."""
    out: list[str] = []
    for entry in items or []:
        text = str(entry.get("text") if isinstance(entry, dict) else entry or "").strip()
        if text:
            out.append(f"<p>{_escape(text)}</p>")
    return "".join(out)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _md_to_html(markdown: str) -> str:
    """The blog ``body`` slot's markdown, rendered to the subset a page body needs.

    Deliberately small and local rather than imported from ``workers.tasks.content``: a
    service importing a worker inverts the dependency, and this is the only slot that
    carries markdown at all (everything else arrives already structured). Handles what
    the body slot is asked to produce - H2/H3, paragraphs, bullet and numbered lists,
    bold and links - and escapes the rest.
    """
    out: list[str] = []
    buffer: list[str] = []
    list_tag = ""

    def flush_para() -> None:
        if buffer:
            out.append(f"<p>{' '.join(buffer)}</p>")
            buffer.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_para()
            flush_list()
            continue
        heading = re.match(r"^(#{2,3})\s+(.*)$", stripped)
        if heading:
            flush_para()
            flush_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        number = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or number:
            flush_para()
            want = "ul" if bullet else "ol"
            if list_tag != want:
                flush_list()
                out.append(f"<{want}>")
                list_tag = want
            item = (bullet or number)
            assert item is not None
            out.append(f"<li>{_inline(item.group(1))}</li>")
            continue
        flush_list()
        buffer.append(_inline(stripped))
    flush_para()
    flush_list()
    return "".join(out)


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    """Escape, then restore the two inline marks a body legitimately uses."""
    safe = _escape(text)
    safe = _BOLD_RE.sub(r"<strong>\1</strong>", safe)
    return _LINK_RE.sub(r'<a href="\2">\1</a>', safe)


def _map_items(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Translate one slot payload into the renderer's field names."""
    out: dict[str, Any] = {}
    if kind in _PROSE_KINDS:
        html = _para_html(data.get("paragraphs"))
        if html:
            out["html"] = html
        return out
    if kind == "body":
        html = _md_to_html(str(data.get("markdown") or ""))
        if html:
            out["html"] = html
        return out
    if kind == "hero":
        out["subhead"] = str(data.get("subheading") or "")
        bullets = [
            {"text": str(b.get("text") if isinstance(b, dict) else b or "").strip()}
            for b in (data.get("bullets") or [])
        ]
        bullets = [b for b in bullets if b["text"]]
        if bullets:
            out["bullets"] = bullets
        label = str(data.get("cta_label") or "").strip()
        if label:
            out["buttons"] = [{"label": label, "url": "#contact"}]
        return out
    if kind == "cta":
        out["text"] = str(data.get("text") or "")
        label = str(data.get("button_label") or "").strip()
        out["button"] = {"label": label or "Get in touch", "url": "#contact"}
        return out

    mapping = _ITEM_MAP.get(kind)
    if mapping is None:
        return out
    src_field, dst_field, subs = mapping
    rows: list[dict[str, str]] = []
    for entry in data.get(src_field) or []:
        if not isinstance(entry, dict):
            continue
        row = {dst: str(entry.get(src, "")).strip() for src, dst in subs}
        if any(row.values()):
            rows.append(row)
    if rows:
        out[dst_field] = rows
    if data.get("intro"):
        out["intro"] = str(data["intro"])
    return out


#: Kinds whose content is DATA THE PRODUCT HOLDS rather than copy the writer produces -
#: the client's NAP, the links to its own other pages. They are filled by
#: :func:`model_from_composed` from what the caller passes it, and like every other kind
#: they are DROPPED when that data turns out to be absent.
#:
#: There is no "the theme will fill it" category any more, and removing it is the fix. It
#: existed for a page whose flat body the publisher plugin decorates; a COMPOSED page
#: publishes as one self-contained document that nothing else writes into, so a slot
#: nothing here can draw is a section heading with blank space under it. Measured on every
#: one of the seven kinds that used to be in this set.
_DATA_KINDS: frozenset[str] = frozenset({"contact", "related"})


def _has_content(kind: str, data: dict[str, Any]) -> bool:
    """Whether this section would draw anything at all."""
    if kind in _PROSE_KINDS or kind == "body":
        return bool(data.get("html"))
    if kind == "hero":
        return bool(data.get("subhead"))
    if kind == "cta":
        return bool(data.get("text"))
    if kind == "contact":
        return any(data.get(k) for k in ("name", "address", "phone", "hours", "email"))
    if kind == "related":
        return bool(data.get("links"))
    mapping = _ITEM_MAP.get(kind)
    if mapping is None:
        # A KIND NOBODY CAN DRAW IS NOT A SECTION. This used to return True for anything
        # unmapped, on the reasoning that an unmapped kind must be chrome the theme fills
        # from live data. That is true of a page whose body the publisher plugin decorates
        # and false of a composed page, which publishes as one self-contained document
        # nothing else writes into - so every such slot published as a heading with blank
        # space under it. Measured on a location page's reviews slot, which passed its
        # evidence gate, was written, and drew nothing.
        return False
    return bool(data.get(mapping[1]))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def assign_images(
    kinds: list[str], images: list[tuple[str, str]]
) -> dict[int, tuple[str, str]]:
    """Which section gets which picture: hero first, then one each, in page order.

    ``images`` is ``[(url, alt), ...]`` in generation order. Returns ``{section index:
    (url, alt)}``. A section gets AT MOST ONE image and no section gets one it cannot use,
    which is the whole difference between an illustrated page and a scattered one.
    """
    if not images:
        return {}
    out: dict[int, tuple[str, str]] = {}
    remaining = list(images)
    for i, kind in enumerate(kinds):
        if kind == "hero" and remaining:
            out[i] = remaining.pop(0)
            break
    if not remaining:
        return out
    ordered = [
        i for pref in _IMAGE_PREFERENCE
        for i, kind in enumerate(kinds)
        if kind == pref and i not in out
    ]
    for index in ordered:
        if not remaining:
            break
        out[index] = remaining.pop(0)
    return out


def image_capacity(kinds: list[str] | tuple[str, ...]) -> int:
    """How many images this page can actually PLACE - what the image planner should make.

    Generating five pictures for a page that can use one is not a cosmetic waste: each is a
    paid call, and the four spare ones used to get injected into the prose anyway, which is
    how a service page ended up with photographs between its paragraphs.
    """
    kinds = list(kinds)
    hero = 1 if "hero" in kinds else 0
    return hero + sum(1 for k in kinds if k in _IMAGE_PREFERENCE)


def _contact_data(nap: dict[str, Any] | None) -> dict[str, Any]:
    """The client's real name, address, phone and hours - never invented, never partial.

    Each field is emitted only when the client actually supplied it, so a business with no
    published hours gets a contact block without an hours line rather than an empty one.
    """
    nap = nap or {}
    out: dict[str, Any] = {}
    for key, *candidates in (
        ("name", "business_name", "name"),
        ("address", "address", "street_address", "address_line_1"),
        ("phone", "phone", "telephone"),
        ("hours", "hours", "opening_hours"),
        ("email", "email", "contact_email"),
    ):
        for candidate in candidates:
            value = str(nap.get(candidate) or "").strip()
            if value:
                out[key] = value
                break
    return out


def _related_data(links: dict[str, str] | None) -> dict[str, Any]:
    """Links to the client's OWN other pages, as label/url pairs.

    Capped at six: a related-pages block is a short, scannable list of next steps, and a
    page listing forty of its siblings is a sitemap nobody reads.
    """
    out = [
        {"label": str(label).strip(), "url": str(url).strip()}
        for label, url in (links or {}).items()
        if str(label).strip() and str(url).strip()
    ]
    return {"links": out[:6]} if out else {}


def model_from_composed(
    sections: list[dict[str, Any]],
    *,
    design: dict[str, Any] | None = None,
    title: str = "",
    images: list[tuple[str, str]] | None = None,
    cta_url: str = "",
    nap: dict[str, Any] | None = None,
    internal_links: dict[str, str] | None = None,
) -> PageModel:
    """Build the page model from the composer's slots, images placed by section.

    ``sections`` is the composer's ``[{kind, layout, heading, data}]``. Sections that
    would render empty are dropped here rather than rendered as empty bands.
    """
    model = PageModel(title=title, design=dict(design or {}))
    usable: list[tuple[str, str, str, dict[str, Any]]] = []
    for raw in sections:
        kind = str(raw.get("kind") or "").strip()
        if not kind:
            continue
        data = _map_items(kind, dict(raw.get("data") or {}))
        # THE TWO KINDS THE PRODUCT FILLS, not the writer. A contact block is the client's
        # real NAP and a related block is links to its own pages; both are data we already
        # hold, and asking a model to produce either is asking it to invent an address.
        if kind == "contact":
            data = {**_contact_data(nap), **data}
        elif kind == "related":
            data = {**_related_data(internal_links), **data}
        if not _has_content(kind, data):
            continue
        usable.append((kind, str(raw.get("layout") or "stacked"),
                       str(raw.get("heading") or ""), data))

    placement = assign_images([k for k, _, _, _ in usable], list(images or []))
    for i, (kind, layout, heading, data) in enumerate(usable):
        if cta_url:
            # The button points at the client's own contact page when we know it, rather
            # than at an anchor that may not exist on their template.
            for key in ("buttons",):
                for button in data.get(key) or []:
                    button["url"] = cta_url
            if isinstance(data.get("button"), dict):
                data["button"]["url"] = cta_url
        image = placement.get(i)
        model.sections.append(
            Section(
                id=f"s{i}_{_slug(kind)}",
                kind=kind,
                layout=layout,
                heading=heading,
                data=data,
                images=[Image(url=image[0], alt=image[1])] if image else [],
            )
        )
    return model
