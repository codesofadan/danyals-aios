"""Inferred layout -> a real, oracle-validated Elementor document (stage 4).

EVERY KEY IS CHECKED AGAINST ELEMENTOR'S OWN REGISTRY BEFORE ANYTHING LEAVES THIS
MODULE. The oracle (`app/services/data/elementor_oracle_4_7.json`) is the controls
registry parsed out of Elementor 4.7's editor bootstrap on the target site, unioned
with the keys the reference page's real `_elementor_data` uses. A settings key the
registry does not know is stored and silently IGNORED by the editor, which is how two
long-standing bugs survived: `title_typography_typography` on headings and
`button_background_color` on buttons are both invalid on 4.7 - the first shipped in two
emitters, and the second means every button this platform has pushed renders with the
default background. The oracle turns that class of bug into a build-time exception.

HYBRID, AS DECIDED: layout, spacing, colour and typography go into REAL settings so
the editor's controls work when clicked; component polish rides on the BEM classes the
layout stage already read off the source (`_css_classes`), styled by the generated
stylesheet (stage 5).

DESKTOP-ONLY FOR NOW, HONESTLY. `*_tablet`/`*_mobile` variants belong here and the
capture already measures three viewports, but the frozen fixture is desktop-only - so
responsive emission lands when the tablet/mobile fixtures do, rather than being faked
from one viewport.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from app.services.design_system import DesignSystem
from app.services.elementor import _IdGen
from app.services.layout_infer import (
    InferredColumn,
    InferredNavbar,
    InferredPage,
    InferredRow,
    InferredSection,
    InferredWidget,
)
from app.services.replica_capability import TargetCapability

#: The WordPress menu a Pro `nav-menu` widget points at. One name, so a replica's
#: header and the menu the publisher registers cannot drift apart.
_NAV_MENU_NAME = "AIOS Replica"

#: PACKAGE DATA, not a test fixture.
#:
#: This lived at `backend/tests/fixtures/elementor/oracle_4_7.json` and was loaded via
#: `parents[2] / "tests" / ...`. That resolves in a source checkout and CANNOT resolve
#: in production: the app runs from the venv (backend/Dockerfile copies only
#: db/migrations and the audit engine into the runtime stage), so `parents[2]` is
#: site-packages and `tests/` was never shipped. Every replication died on
#:   FileNotFoundError: /opt/venv/.../site-packages/tests/fixtures/elementor/oracle_4_7.json
#: while the whole test suite passed, because a test run always has the checkout.
#:
#: pyproject's force-include comment predicted this exact failure for the doctrine
#: corpus ("present in every test run and absent in production"). Same trap, second
#: file. Inside `app/` it is carried by `packages = ["app"]`, so it needs no
#: force-include entry and cannot be forgotten again.
#:
#: The TESTS read it through `load_oracle()` too, so there is ONE copy: a test can
#: never pass against a file production does not have.
_ORACLE_PATH = pathlib.Path(__file__).resolve().parent / "data" / "elementor_oracle_4_7.json"


class UnknownSettingError(ValueError):
    """A settings key Elementor's registry does not know. Refused at build time."""


def load_oracle() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_ORACLE_PATH.read_text())
    return data


_PX_RE = re.compile(r"^(-?[\d.]+)px$")


def _px(value: str) -> int | None:
    m = _PX_RE.match((value or "").strip())
    return round(float(m.group(1))) if m else None


def _pad4(style: dict[str, str], prefix: str = "padding") -> dict[str, Any] | None:
    sides = {}
    for side in ("Top", "Right", "Bottom", "Left"):
        v = _px(style.get(f"{prefix}{side}", ""))
        sides[side.lower()] = v if v is not None else 0
    if not any(sides.values()):
        return None
    return {"unit": "px", **{k: str(v) for k, v in sides.items()},
            "isLinked": len(set(sides.values())) == 1}


def _colour(value: str) -> str:
    from app.services.design_system import to_hex

    return to_hex(value)


def _bg_image_url(style: dict[str, str]) -> str:
    m = re.search(r'url\(["\']?([^"\')]+)["\']?\)', style.get("backgroundImage", ""))
    return m.group(1) if m else ""


_GRAD_RE = re.compile(
    r"linear-gradient\(\s*(?:(-?[\d.]+)deg\s*,)?\s*(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8})"
    r".*?(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8})[^(]*\)$"
)


def _gradient(scrim: str) -> dict[str, Any] | None:
    """A measured ::before gradient as Elementor's own gradient controls.

    Only the first and last stops carry over - Elementor's control is two-stop. A
    scrim with more stops degrades to its endpoints, which reads correctly for the
    fade-over-image pattern this exists for.
    """
    if not scrim or "gradient" not in scrim:
        return None
    m = _GRAD_RE.search(scrim.strip())
    if not m:
        return None
    angle, start, end = m.groups()
    return {
        "background_background": "gradient",
        "background_color": start,
        "background_color_b": end,
        "background_gradient_type": "linear",
        "background_gradient_angle": {"unit": "deg",
                                      "size": round(float(angle)) if angle else 180},
    }


def _typography(settings: dict[str, Any], prefix: str, family: str, size_px: int | None,
                weight: str = "") -> None:
    """The `custom` switch plus the group keys, under the given prefix.

    The prefix comes from the ORACLE per widget, not from convention: on 4.7 the
    heading widget's group is plain `typography_*`, and the `title_typography_*` keys
    two earlier emitters wrote are simply not in its registry.
    """
    if not family and size_px is None and not weight:
        return
    settings[f"{prefix}typography_typography"] = "custom"
    if family:
        settings[f"{prefix}typography_font_family"] = family
    if size_px is not None:
        settings[f"{prefix}typography_font_size"] = {"unit": "px", "size": size_px}
    if weight:
        settings[f"{prefix}typography_font_weight"] = weight


# --------------------------------------------------------------------------- #
# Widget builders - one per closed-vocabulary type
# --------------------------------------------------------------------------- #
def _w_heading(w: InferredWidget, ds: DesignSystem,
               responsive: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    node, style = w.node, w.node.get("s") or {}
    level = node.get("t", "h2")
    # An h3 whose words live on nested spans has no own text - join the subtree in
    # document order, or the page's main headline arrives as an empty widget.
    text = node.get("txt") or _inline_text(node)
    out: dict[str, Any] = {
        "title": text,
        "header_size": level if level in ("h1", "h2", "h3", "h4", "h5", "h6") else "h2",
    }
    colour = _colour(style.get("color", "")) or ds.palette.get("heading", "")
    if colour:
        out["title_color"] = colour
    desktop_px = _px(style.get("fontSize", ""))
    _typography(out, "", style.get("fontFamily", "").split(",")[0].strip('"\' ')
                or ds.fonts.get("heading", ""), desktop_px,
                style.get("fontWeight", ""))
    # RESPONSIVE, FROM MEASUREMENT. The tablet and mobile captures resolve their own
    # font sizes for the same heading (matched by its text); a variant key is
    # emitted only where the measured value differs from desktop, because emitting
    # every variant lights the "overridden" badge on every control and triples the
    # tree for nothing.
    for device in ("tablet", "mobile"):
        measured = (responsive or {}).get(device, {}).get(text)
        if measured and desktop_px and abs(measured - desktop_px) >= 2:
            out[f"typography_font_size_{device}"] = {"unit": "px", "size": measured}
    align = style.get("textAlign", "")
    if align in ("center", "right"):
        out["align"] = align
    return out


def _inline_text(node: dict[str, Any]) -> str:
    """The node's whole inline text, children merged in document order.

    "4.9" with a nested small "/5" is one piece of text; no space is inserted before
    leading punctuation so it reads 4.9/5, not 4.9 /5.
    """
    parts: list[str] = []

    def visit(n: dict[str, Any]) -> None:
        t = (n.get("txt") or "").strip()
        if t:
            if parts and t[0] in "/.,;:!?%)":
                parts[-1] = parts[-1] + t
            else:
                parts.append(t)
        for k in n.get("kids") or []:
            visit(k)

    visit(node)
    return " ".join(parts)


def _w_text(w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    style = w.node.get("s") or {}
    out: dict[str, Any] = {"editor": f"<p>{_inline_text(w.node)}</p>"}
    colour = _colour(style.get("color", "")) or ds.palette.get("text", "")
    if colour:
        out["text_color"] = colour
    _typography(out, "", ds.fonts.get("body", ""), _px(style.get("fontSize", "")))
    return out


def _w_image(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    node = w.node
    style = node.get("s") or {}
    url = node.get("src") or _bg_image_url(style)
    if url.startswith("data:"):
        url = ""  # a lazy-loader placeholder, never a publishable source
    out: dict[str, Any] = {"image": {"url": url, "id": "", "alt": node.get("alt") or ""},
                           "image_size": "full"}
    # The measured box IS the size the source renders - without it Elementor shows
    # the file at natural size, and an 86px service icon arrived as a full-width
    # graphic. `width` is the image widget's own control, so it stays editable.
    # EXCEPT a background tile drawn with `contain`: its box is the frame, not the
    # picture (a 170px review badge sat in a 1006px slide; box-width blew it up).
    box = node.get("box") or [0, 0, 0, 0]
    contained = (not node.get("src")
                 and "contain" in (style.get("backgroundSize") or ""))
    if box[2] and box[2] >= 16 and not contained:
        out["width"] = {"unit": "px", "size": int(box[2])}
    if contained and "50%" in (style.get("backgroundPosition") or ""):
        out["align"] = "center"  # the frame centred its picture; keep that
    return out


def _subtree_text(node: dict[str, Any]) -> str:
    parts = [node.get("txt") or ""]
    for k in node.get("kids") or []:
        parts.append(_subtree_text(k))
    return " ".join(x for x in parts if x).strip()


def _parse_shadow(raw: str) -> dict[str, Any] | None:
    """A computed box-shadow -> Elementor's shadow object (first shadow only).

    Chrome serialises colour-first: ``rgba(0, 0, 0, 0.5) 0px 0px 10px 0px``. The
    hard-offset black shadow on the reference's yellow CTAs and the soft ring on
    its floating cards are both DESIGN, not decoration to drop.
    """
    if not raw or raw == "none":
        return None
    m = re.match(
        r"(rgba?\([^)]*\)|#\S+)\s+(-?[\d.]+)px\s+(-?[\d.]+)px\s+(-?[\d.]+)px"
        r"(?:\s+(-?[\d.]+)px)?",
        raw.strip(),
    )
    if not m:
        return None
    colour, hx, vy, blur, spread = m.groups()
    return {
        "horizontal": round(float(hx)), "vertical": round(float(vy)),
        "blur": round(float(blur)), "spread": round(float(spread or 0)),
        "color": colour,
    }


def _w_button(w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    node, style = w.node, w.node.get("s") or {}
    out: dict[str, Any] = {
        "text": node.get("txt") or _subtree_text(node),
        "link": {"url": node.get("href") or "", "is_external": "", "nofollow": ""},
    }
    # `background_color`, NOT `button_background_color`: the 4.7 registry knows only
    # the former. The platform's markdown emitter has shipped the latter for weeks,
    # which is why its buttons render with the theme default.
    bg = _colour(style.get("backgroundColor", "")) or ds.palette.get("accent", "")
    if bg:
        out["background_color"] = bg
    fg = _colour(style.get("color", ""))
    if fg:
        out["button_text_color"] = fg
    radius = _px(style.get("borderRadius", ""))
    if radius is not None:
        out["border_radius"] = {"unit": "px", "top": str(radius), "right": str(radius),
                                "bottom": str(radius), "left": str(radius),
                                "isLinked": True}
    _typography(out, "", ds.fonts.get("body", ""), _px(style.get("fontSize", "")))
    shadow = _parse_shadow(style.get("boxShadow", ""))
    if shadow:
        out["button_box_shadow_box_shadow_type"] = "yes"
        out["button_box_shadow_box_shadow"] = shadow
    return out


def _w_icon_list(w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    # per-item text is the ITEM's whole inline subtree: an <li> whose label sits on
    # a nested <a><span> captured as an empty item, and three city cards rendered
    # with headings and no services under them
    items = [t for t in (_inline_text(k) for k in (w.node.get("kids") or [])) if t]
    if not items and w.node.get("txt"):
        items = [w.node["txt"]]
    out: dict[str, Any] = {"icon_list": [
        {"text": t, "selected_icon": {"value": "fas fa-check", "library": "fa-solid"}}
        for t in items
    ]}
    if ds.palette.get("accent"):
        out["icon_color"] = ds.palette["accent"]
    return out


def _w_star_rating(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    text = w.node.get("txt") or ""
    stars = text.count("★") + text.count("⭐")
    return {"rating": min(5, stars) or 5}


def _w_spacer(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    return {"space": {"unit": "px", "size": max(10, w.node.get("box", [0, 0, 0, 40])[3])}}


def _w_divider(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    style = w.node.get("s") or {}
    out: dict[str, Any] = {"style": "solid", "weight": {"unit": "px", "size": 1}}
    try:
        weight = round(float((style.get("borderTopWidth") or "1").rstrip("px")))
        if weight:
            out["weight"] = {"unit": "px", "size": min(weight, 10)}
    except ValueError:
        pass
    colour = _colour(style.get("borderTopColor", ""))
    if colour:
        out["color"] = colour
    return out


def _w_testimonial(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    return {"testimonial_content": w.node.get("txt") or ""}


def _w_maps(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    return {"address": w.node.get("src") or ""}


def _w_icon(_w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    out: dict[str, Any] = {
        "selected_icon": {"value": "fas fa-circle", "library": "fa-solid"}}
    if ds.palette.get("accent"):
        out["primary_color"] = ds.palette["accent"]
    return out


def _w_social(_w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    return {"social_icon_list": []}


def _w_accordion(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    kids = w.node.get("kids") or []
    tabs = []
    for i in range(0, len(kids) - 1, 2):
        tabs.append({"_id": f"tab{i}", "tab_title": kids[i].get("txt") or "",
                     "tab_content": kids[i + 1].get("txt") or ""})
    if not tabs and w.node.get("txt"):
        tabs = [{"_id": "tab0", "tab_title": w.node["txt"], "tab_content": ""}]
    return {"tabs": tabs}


_BUILDERS = {
    "heading": _w_heading, "text-editor": _w_text, "image": _w_image,
    "button": _w_button, "icon-list": _w_icon_list, "star-rating": _w_star_rating,
    "spacer": _w_spacer, "divider": _w_divider, "testimonial": _w_testimonial,
    "google_maps": _w_maps, "icon": _w_icon, "social-icons": _w_social,
    "accordion": _w_accordion,
    # icon-box needs its parts split apart; until a splitter exists it degrades to
    # heading+text upstream, so no builder here - and the closed switch catches it.
}


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _widget(w: InferredWidget, ds: DesignSystem, ids: _IdGen,
            responsive: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    builder = _BUILDERS.get(w.type)
    if builder is None:
        raise UnknownSettingError(f"no builder for widget type {w.type!r}")
    settings = (_w_heading(w, ds, responsive) if w.type == "heading"
                else builder(w, ds))
    if w.gap_below >= 0:
        # the measured distance to the next widget IS the design's rhythm; leaving
        # it to the kit default (20px on everything) is why the rebuild breathed
        # looser than the source everywhere
        settings["_margin"] = {"unit": "px", "top": "0", "right": "0",
                               "bottom": str(w.gap_below), "left": "0",
                               "isLinked": False}
    if w.classes:
        settings["_css_classes"] = " ".join(w.classes[:4])
    return {
        "id": ids.next(f"{w.type}:{(w.node.get('txt') or w.node.get('src') or '')[:40]}"),
        "elType": "widget",
        "widgetType": w.type,
        "settings": settings,
    }


def _column(col: InferredColumn, ds: DesignSystem, ids: _IdGen,
            container_px: int,
            responsive: dict[str, dict[str, int]] | None = None,
            mobile_pos: dict[str, tuple[int, int]] | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "_column_size": col.width_pct,
        # `_inline_size` is what the editor's drag handle reads; without it the
        # handle shows a preset default rather than the real width.
        "_inline_size": col.width_pct,
    }
    if col.classes:
        settings["_css_classes"] = " ".join(col.classes[:4])
    bg = _colour(col.background)
    if bg and bg != ds.palette.get("background"):
        settings["background_background"] = "classic"
        settings["background_color"] = bg
    if any(col.pad):
        top_, right_, bottom_, left_ = col.pad
        settings["padding"] = {"unit": "px", "top": str(top_), "right": str(right_),
                              "bottom": str(bottom_), "left": str(left_),
                              "isLinked": False}
    if col.radius_px:
        r = str(col.radius_px)
        settings["border_radius"] = {"unit": "px", "top": r, "right": r,
                                     "bottom": r, "left": r, "isLinked": True}
    if col.border_px:
        # the rounded-OUTLINE card: the outline is the design, and it maps onto
        # the column's own border group so the editor's controls stay live
        bw = str(col.border_px)
        settings["border_border"] = (col.border_style
                                     if col.border_style in ("solid", "double",
                                                             "dashed", "dotted")
                                     else "solid")
        settings["border_width"] = {"unit": "px", "top": bw, "right": bw,
                                    "bottom": bw, "left": bw, "isLinked": True}
        border_colour = _colour(col.border_color)
        if border_colour:
            settings["border_color"] = border_colour
    col_shadow = _parse_shadow(col.shadow)
    if col_shadow:
        settings["box_shadow_box_shadow_type"] = "yes"
        settings["box_shadow_box_shadow"] = col_shadow
    grad = _gradient(col.scrim)
    if grad:
        settings.update(grad)
    elements: list[dict[str, Any]] = []
    if col.rows:
        for row in col.rows:
            elements.append(_row_as_inner_section(row, ds, ids, container_px, responsive, mobile_pos))
    else:
        elements = [_widget(w, ds, ids, responsive) for w in col.widgets]
        # BUTTON ALIGNMENT is geometric: Elementor left-aligns by default, but the
        # measured centre of a CTA sitting on the column's centre line says the
        # author centred it. The builder cannot know this - only the column can.
        col_centre = col.x + col.width_px / 2
        for w, el in zip(col.widgets, elements, strict=True):
            if w.type != "button":
                continue
            bx, _, bw, _ = (w.node.get("box") or [0, 0, 0, 0])
            if not bw or bw >= col.width_px * 0.9:
                continue
            if abs((bx + bw / 2) - col_centre) <= max(12.0, col.width_px * 0.04):
                el["settings"]["align"] = "center"
    return {
        "id": ids.next(f"col:{col.x}:{col.width_pct}"),
        "elType": "column",
        "settings": settings,
        "elements": elements,
    }


def _row_as_inner_section(row: InferredRow, ds: DesignSystem, ids: _IdGen,
                          container_px: int,
                          responsive: dict[str, dict[str, int]] | None = None,
                          mobile_pos: dict[str, tuple[int, int]] | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {"gap": "default"}
    if row.structure:
        settings["structure"] = row.structure
    columns = [_column(c, ds, ids, container_px, responsive, mobile_pos)
               for c in row.columns]
    if mobile_pos and _row_stays_inline_on_mobile(row, mobile_pos):
        share = max(1, 100 // len(columns))
        for el in columns:
            el["settings"]["_inline_size_mobile"] = share
    return {
        "id": ids.next(f"inner:{row.y}"),
        "elType": "section",
        "isInner": True,
        "settings": settings,
        "elements": columns,
    }


def _section(section: InferredSection, ds: DesignSystem, ids: _IdGen,
             container_px: int,
             responsive: dict[str, dict[str, int]] | None = None,
             mobile_pos: dict[str, tuple[int, int]] | None = None,
             band_pad: dict[str, dict[str, tuple[int, int]]] | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    anchor = _section_anchor(section)
    first_multi = next((r for r in section.rows if len(r.columns) > 1), None)
    if first_multi and first_multi.structure:
        settings["structure"] = first_multi.structure
    if section.full_bleed:
        # `stretch_section` breaks the BAND out of the theme's content box - without
        # it the whole rebuild rendered inside Astra's narrow blog column (the
        # owner's own screenshot of that is why this exists). The CONTENT stays
        # boxed: pairing stretch with layout:"full_width" ran the text edge-to-edge
        # and off the left viewport - a full-bleed band with boxed content is what
        # the source page actually is.
        settings["stretch_section"] = "section-stretched"
        settings["layout"] = "boxed"
    settings["content_width"] = {"unit": "px", "size": container_px}
    bg = _colour(section.background)
    if bg:
        settings["background_background"] = "classic"
        settings["background_color"] = bg
    if section.background_image and "elementor/assets/images/placeholder" not in section.background_image:
        # A real photograph as a band's backdrop is the common custom-site pattern
        # and cover is right for it. Elementor's own placeholder art blown up to
        # cover a 600px band is just a giant grey blob - skip it, the colour carries
        # the band.
        settings["background_background"] = "classic"
        settings["background_image"] = {"url": section.background_image, "id": ""}
        settings["background_size"] = "cover"
        settings["background_position"] = "center center"
    if section.pad_top or section.pad_bottom:
        # the page's own vertical rhythm, measured from where content actually sits
        # inside the band - not Elementor's default breathing
        settings["padding"] = {
            "unit": "px", "top": str(section.pad_top), "right": "0",
            "bottom": str(section.pad_bottom), "left": "0", "isLinked": False,
        }
        # ...and the rhythm the SOURCE uses at each smaller breakpoint, rather than
        # letting Elementor inherit the desktop figure down to a 390px phone. See
        # responsive_band_padding: on the reference page every measured band shrank
        # from 88px to 10-25px, so inheriting desktop is wrong on every section.
        for device, suffix in (("tablet", "_tablet"), ("mobile", "_mobile")):
            measured = (band_pad or {}).get(device, {}).get(anchor)
            if not measured:
                continue
            top, bottom = measured
            if (top, bottom) == (section.pad_top, section.pad_bottom):
                continue  # identical to desktop; an explicit variant would be noise
            settings[f"padding{suffix}"] = {
                "unit": "px", "top": str(top), "right": "0",
                "bottom": str(bottom), "left": "0", "isLinked": False,
            }
    if section.classes:
        settings["_css_classes"] = " ".join(section.classes[:4])
    if section.element_id:
        settings["_element_id"] = section.element_id

    # One row -> its columns ARE the section's columns. Many rows -> a single
    # full-width column of inner sections, which is Elementor's own idiom for
    # stacked bands inside one background.
    if len(section.rows) == 1:
        elements = [_column(c, ds, ids, container_px, responsive, mobile_pos)
                    for c in section.rows[0].columns]
        if mobile_pos and _row_stays_inline_on_mobile(section.rows[0], mobile_pos):
            share = max(1, 100 // len(elements))
            for el in elements:
                el["settings"]["_inline_size_mobile"] = share
    else:
        inner = [_row_as_inner_section(r, ds, ids, container_px, responsive, mobile_pos)
                 if len(r.columns) > 1 else
                 _column(r.columns[0], ds, ids, container_px, responsive, mobile_pos)
                 for r in section.rows]
        wrapped: list[dict[str, Any]] = []
        for el in inner:
            if el["elType"] == "column":
                wrapped.append(el)
            else:
                wrapped.append(el)
        elements = [{
            "id": ids.next(f"colwrap:{section.y}"),
            "elType": "column",
            "settings": {"_column_size": 100, "_inline_size": 100},
            "elements": wrapped,
        }]
        # a column may not directly hold a column; re-wrap plain columns as inner
        # sections of one column each
        for i, el in enumerate(wrapped):
            if el["elType"] == "column":
                wrapped[i] = {
                    "id": ids.next(f"innerwrap:{i}"),
                    "elType": "section", "isInner": True,
                    "settings": {"gap": "default"},
                    "elements": [el],
                }
    return {
        "id": ids.next(f"sec:{section.y}"),
        "elType": "section",
        "settings": settings,
        "elements": elements,
    }


def build_tree(page: InferredPage, ds: DesignSystem,
               responsive: dict[str, dict[str, int]] | None = None,
               mobile_pos: dict[str, tuple[int, int]] | None = None,
               band_pad: dict[str, dict[str, tuple[int, int]]] | None = None
               ) -> list[dict[str, Any]]:
    ids = _IdGen()
    return [_section(s, ds, ids, page.container_px, responsive, mobile_pos, band_pad)
            for s in page.sections]


def mobile_text_positions(captures: dict[str, dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """{text: (x, y)} from the mobile capture - the facts behind keep-inline-on-mobile.

    Elementor stacks columns on mobile by default, which is right for most rows. The
    reference stats trio measurably STAYS inline at 390px, and stacking it breaks the
    card. Whether a row keeps its columns side by side is decided by whether its
    columns' texts still share a y-band in the mobile capture - measured, never
    assumed.
    """
    mobile = captures.get("mobile")
    out: dict[str, tuple[int, int]] = {}
    if not mobile:
        return out

    # AMBIGUOUS TEXT IDENTIFIES NOTHING. This kept the FIRST position per text and
    # ignored every later one, so a row of cards whose buttons all read "View more"
    # had every column resolve to the SAME coordinates - identical y, zero spread,
    # "they share a band", forced side by side at 33% width on a 390px phone.
    # Measured on the reference capture: 21 of 160 distinct strings repeat, and the
    # repeats are exactly the ones that would appear across a row of cards -
    # "View more" 4x spread over 1,287px, "Get a quote" 3x over 10,343px, "Read the
    # guide" 3x over 802px, and an icon-font glyph 45x over 4,789px.
    #
    # So count first and keep only the texts that occur ONCE. A column whose anchor
    # is ambiguous now finds nothing, and `_row_stays_inline_on_mobile` already
    # returns False on a missing anchor - which is the right default, because
    # Elementor stacks columns on mobile unless we can PROVE the source does not.
    counts: dict[str, int] = {}
    first: dict[str, tuple[int, int]] = {}

    def walk(n: dict[str, Any]) -> None:
        t = (n.get("txt") or "").strip()
        if t:
            counts[t] = counts.get(t, 0) + 1
            if t not in first:
                first[t] = (int(n["box"][0]), int(n["box"][1]))
        for k in n.get("kids") or []:
            walk(k)

    walk(mobile)
    out = {t: xy for t, xy in first.items() if counts[t] == 1}
    return out


def _row_stays_inline_on_mobile(row: InferredRow,
                                positions: dict[str, tuple[int, int]]) -> bool:
    if len(row.columns) < 2:
        return False
    ys: list[int] = []
    for col in row.columns:
        first = next((w for w in col.widgets
                      if (w.node.get("txt") or "").strip()), None)
        if first is None:
            return False
        pos = positions.get((first.node.get("txt") or "").strip())
        if pos is None:
            return False
        ys.append(pos[1])
    return max(ys) - min(ys) <= 30


def responsive_band_padding(
    captures: dict[str, dict[str, Any]],
) -> dict[str, dict[str, tuple[int, int]]]:
    """{device: {anchor text: (padTop, padBottom)}} - a band's OWN vertical rhythm
    at each non-desktop viewport.

    THE DEFECT THIS CLOSES. Three viewports were captured and the tablet/mobile ones
    were mined for exactly two facts: heading font sizes and mobile text positions.
    Every other measurement was discarded, so a rebuilt page carried its DESKTOP
    spacing to every breakpoint. Measured on the reference capture, that is not a
    small error and it is not occasional: of 153 text anchors present at all three
    viewports, **153** had mobile band padding differing from desktop - the source
    uses 88px of vertical padding on a desktop band and 10-25px on a phone. Shipping
    88px to a 390px screen puts most of a phone viewport's height into dead space at
    every single section boundary, which is precisely what "not properly responsive"
    looks like to the person holding the phone.

    Anchored by TEXT for the same reason `responsive_heading_sizes` is: node identity
    does not survive across viewports (the prune keeps different wrappers at different
    widths) but a band's copy is the same page-fact everywhere it renders.

    A "band" is a node spanning nearly the full page width, and the OUTERMOST one that
    declares padding wins - an inner card's padding is not the section's rhythm. Text
    with no measured band contributes nothing, so a section that cannot be matched
    simply keeps its desktop padding: the behaviour before this existed, never worse.
    """
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for device, root in captures.items():
        # THE PAGE WIDTH IS THE ROOT'S WIDTH, never the widest node in the tree.
        # A horizontally-overflowing element - a carousel track, a marquee - is
        # legitimately far wider than the viewport: the reference tablet capture
        # (834px) contains a 2,468px track, so a max-of-all-widths page width put
        # the band threshold at 2,221px and matched NOTHING. This function silently
        # returned an empty map and the whole responsive pass was a no-op.
        page_w = int((root.get("box") or [0, 0, 0, 0])[2])
        if not page_w:
            out[device] = {}
            continue

        found: dict[str, tuple[int, int]] = {}

        def walk(n: dict[str, Any], band: tuple[int, int] | None,
                 _found: dict[str, tuple[int, int]] = found, _pw: int = page_w) -> None:
            style = n.get("s") or {}
            width = int((n.get("box") or [0, 0, 0, 0])[2])
            # OUTERMOST band wins: only adopt a new one where none is in force.
            if band is None and width >= _pw * 0.9:
                top = _px(style.get("paddingTop", "")) or 0
                bottom = _px(style.get("paddingBottom", "")) or 0
                if top or bottom:
                    band = (top, bottom)
            text = (n.get("txt") or "").strip()
            if text and band is not None and text not in _found:
                _found[text] = band
            for k in n.get("kids") or []:
                walk(k, band)

        walk(root, None)
        out[device] = found
    return out


def _section_anchor(section: InferredSection) -> str:
    """The first piece of copy inside a section - its identity across viewports."""
    for row in section.rows:
        for col in row.columns:
            # `all_columns()` walks a column and the columns nested inside its rows,
            # so a section whose copy sits in an inner section still finds an anchor.
            for nested in col.all_columns():
                for widget in nested.widgets:
                    text = (widget.node.get("txt") or "").strip()
                    if text:
                        return text
    return ""


def responsive_heading_sizes(captures: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    """{device: {heading text: font px}} from the tablet/mobile captures.

    Matched by TEXT because node identity does not survive across viewports - the
    prune keeps different wrappers at different widths - while a heading's text is
    the same page-fact everywhere it renders.

    THE KEY MUST BE THE ONE `_w_heading` LOOKS UP WITH, and it was not. This walk
    required `n["txt"]` and keyed on it; `_w_heading` titles from
    ``node.get("txt") or _inline_text(node)``. A heading whose words live on nested
    spans - "Comfort that feels like <em>home</em>", the hero headline pattern - has
    no own text, so it was never entered in this map at all and its lookup could
    never hit. Measured on the reference capture: 12 of 37 headings, 32%, and they
    are exactly the large display headings whose desktop size most needs reducing on
    a phone. Both sides now derive the key identically.
    """
    out: dict[str, dict[str, int]] = {}
    for device, root in captures.items():
        sizes: dict[str, int] = {}

        def walk(n: dict[str, Any], _sizes: dict[str, int] = sizes) -> None:
            if n.get("t") in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = n.get("txt") or _inline_text(n)
                px = _px((n.get("s") or {}).get("fontSize", ""))
                if text and px:
                    _sizes[text] = px
            for k in n.get("kids") or []:
                walk(k)

        walk(root)
        out[device] = sizes
    return out


# --------------------------------------------------------------------------- #
# Validation - the gate nothing skips
# --------------------------------------------------------------------------- #
_SECTION_EXTRA = frozenset({"structure", "layout", "content_width", "gap"})


def validate_tree(tree: list[dict[str, Any]], oracle: dict[str, Any] | None = None) -> None:
    """Raise on any settings key Elementor 4.7's registry does not know.

    An unknown key is not an error to Elementor - it is stored and silently ignored,
    which is worse: the page renders wrong with nothing to see in any log. Two real
    bugs shipped that way. Here it is an exception with the exact key named.
    """
    oracle = oracle or load_oracle()
    common = set(oracle.get("common_keys", []))
    section_ok = set(oracle.get("section_keys", [])) | common | _SECTION_EXTRA
    column_ok = set(oracle.get("column_keys", [])) | common
    widget_keys = {k: set(v) | common for k, v in oracle.get("widget_keys", {}).items()}

    def check(node: dict[str, Any], path: str) -> None:
        el = node.get("elType")
        settings = node.get("settings") or {}
        if el == "widget":
            wt = node.get("widgetType") or ""
            allowed = widget_keys.get(wt)
            if allowed is None:
                raise UnknownSettingError(f"{path}: widget type {wt!r} is not in the oracle")
        elif el == "section":
            allowed = section_ok
        elif el == "column":
            allowed = column_ok
        else:
            raise UnknownSettingError(f"{path}: unknown elType {el!r}")
        for key in settings:
            # Responsive variants store as `<key>_tablet` / `<key>_mobile`; the
            # registry lists base control ids. A variant is valid iff its base is.
            base = key
            for suffix in ("_tablet", "_mobile", "_laptop", "_widescreen"):
                if key.endswith(suffix):
                    base = key[: -len(suffix)]
                    break
            if base not in allowed:
                raise UnknownSettingError(
                    f"{path}: {el}{'/' + node.get('widgetType', '') if el == 'widget' else ''} "
                    f"settings key {key!r} (base {base!r}) is not in Elementor 4.7's "
                    "registry - it would be stored and silently ignored"
                )
        if not node.get("id"):
            raise UnknownSettingError(f"{path}: node has no id")
        for i, child in enumerate(node.get("elements") or []):
            check(child, f"{path}.{i}")

    for i, node in enumerate(tree):
        check(node, f"[{i}]")


def to_json(tree: list[dict[str, Any]]) -> str:
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------- #
# The navbar - emitted from what was recognised
# --------------------------------------------------------------------------- #
def build_navbar(nav: InferredNavbar, ds: DesignSystem,
                 container_px: int,
                 capability: TargetCapability | None = None) -> tuple[dict[str, Any], list[str]]:
    """The recognised header as ONE editable Elementor section.

    BUILT TO WHAT THE TARGET CAN RENDER. When the site has Elementor Pro's
    ``nav-menu`` widget the header is rebuilt as a REAL menu - the thing the
    source actually is, with Elementor's own dropdown and mobile-drawer behaviour.
    When it does not, the menu degrades to an inline ``icon-list``: horizontal,
    one item per link, every label and URL a real editor field. That fallback is
    faithful in content and not in behaviour, so it is RETURNED AS A NOTE rather
    than left for someone to notice.

    This used to assume the free tier for every client, which meant a site paying
    for Pro got a list of links where it had a navigation menu.

    Returns ``(section, notes)``.
    """
    ids = _IdGen()
    columns: list[dict[str, Any]] = []

    def col(widgets: list[dict[str, Any]], pct: int) -> None:
        settings: dict[str, Any] = {"_column_size": pct, "_inline_size": pct,
                                    "content_position": "center"}
        columns.append({"id": ids.next(f"navcol:{len(columns)}"), "elType": "column",
                        "settings": settings, "elements": widgets})

    logo_widgets: list[dict[str, Any]] = []
    if nav.logo_src:
        logo_node: dict[str, Any] = {
            "t": "img", "box": [0, 0, nav.logo_width or 160, nav.height],
            "src": nav.logo_src, "alt": "logo", "s": {}, "kids": [],
        }
        logo_widgets.append(_widget(
            InferredWidget(type="image", node=logo_node), ds, ids))
    elif nav.logo_text:
        logo_node = {"t": "h4", "box": [0, 0, nav.logo_width or 200, 40],
                     "txt": nav.logo_text, "s": {}, "kids": []}
        logo_widgets.append(_widget(
            InferredWidget(type="heading", node=logo_node), ds, ids))

    cap = capability or TargetCapability.free_tier()
    notes: list[str] = []
    menu_widgets: list[dict[str, Any]] = []
    if nav.links:
        widget_type, degraded = cap.resolve("nav")
        colour = _colour(nav.link_color)
        if widget_type == "nav-menu":
            # THE REAL THING. Elementor Pro's nav-menu renders a registered
            # WordPress menu, so the tree references one by name rather than
            # carrying the links inline; the publisher creates it from the same
            # recognised links (the plugin's /site route already builds menus).
            # Layout mirrors what was measured off the source header.
            menu_settings: dict[str, Any] = {
                "layout": "horizontal",
                "menu_name": _NAV_MENU_NAME,
                "align_items": "center",
                "pointer": "none",
            }
            if colour:
                menu_settings["color_menu_item"] = colour
            menu_widgets.append({"id": ids.next("navmenu"), "elType": "widget",
                                 "widgetType": "nav-menu", "settings": menu_settings})
        else:
            items = []
            for link in nav.links:
                items.append({
                    "text": link.text,
                    "selected_icon": {"value": "", "library": ""},
                    "link": {"url": link.href, "is_external": "", "nofollow": ""},
                })
            list_settings: dict[str, Any] = {
                "view": "inline",
                "icon_list": items,
                "space_between": {"unit": "px", "size": 12},
            }
            if colour:
                list_settings["text_color"] = colour
            menu_widgets.append({"id": ids.next("navmenu"), "elType": "widget",
                                 "widgetType": "icon-list", "settings": list_settings})
            if degraded:
                notes.append(degraded)

    cta_widgets: list[dict[str, Any]] = []
    if nav.cta_node is not None:
        cta = _widget(InferredWidget(type="button", node=nav.cta_node), ds, ids)
        cta["settings"]["align"] = "right"
        cta_widgets.append(cta)

    # Column split mirrors the recognised regions; the fallbacks keep a partial
    # recognition publishable (logo only, menu only...).
    if logo_widgets and menu_widgets and cta_widgets:
        col(logo_widgets, 25)
        col(menu_widgets, 50)
        col(cta_widgets, 25)
    elif logo_widgets and menu_widgets:
        col(logo_widgets, 30)
        col(menu_widgets, 70)
    elif menu_widgets:
        col(menu_widgets, 100)
    else:
        col(logo_widgets or cta_widgets or
            [{"id": ids.next("navspacer"), "elType": "widget",
              "widgetType": "spacer", "settings": {"space": {"unit": "px", "size": 10}}}], 100)

    settings: dict[str, Any] = {
        "stretch_section": "section-stretched",
        "layout": "boxed",
        "content_width": {"unit": "px", "size": container_px},
        "padding": {"unit": "px", "top": "10", "right": "0",
                    "bottom": "10", "left": "0", "isLinked": False},
        # The marker the page-scoped guard rule keys on. Measured necessity: the
        # test site's own custom CSS hides ANY top-level section holding an
        # inline icon-list (an unscoped rule meant for one of its own pages) -
        # a client site's stylesheet must not be able to disappear the navbar.
        # `css_classes`, NOT `_css_classes`: sections name the control without
        # the underscore (the widget spelling stored fine and rendered nothing).
        "css_classes": "aios-replica-nav",
    }
    if len(columns) > 1:
        settings["structure"] = f"{len(columns)}0"
    bg = _colour(nav.background)
    if bg:
        settings["background_background"] = "classic"
        settings["background_color"] = bg
    section = {"id": ids.next("navbar"), "elType": "section",
               "settings": settings, "elements": columns}
    return section, notes
