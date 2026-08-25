"""Inferred layout -> a real, oracle-validated Elementor document (stage 4).

EVERY KEY IS CHECKED AGAINST ELEMENTOR'S OWN REGISTRY BEFORE ANYTHING LEAVES THIS
MODULE. The oracle (`tests/fixtures/elementor/oracle_4_7.json`) is the controls
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
    InferredPage,
    InferredRow,
    InferredSection,
    InferredWidget,
)

_ORACLE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests" / "fixtures" / "elementor" / "oracle_4_7.json"
)


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
    text = node.get("txt") or ""
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


def _w_text(w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    style = w.node.get("s") or {}
    out: dict[str, Any] = {"editor": f"<p>{w.node.get('txt') or ''}</p>"}
    colour = _colour(style.get("color", "")) or ds.palette.get("text", "")
    if colour:
        out["text_color"] = colour
    _typography(out, "", ds.fonts.get("body", ""), _px(style.get("fontSize", "")))
    return out


def _w_image(w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    node = w.node
    url = node.get("src") or _bg_image_url(node.get("s") or {})
    return {"image": {"url": url, "id": "", "alt": node.get("alt") or ""},
            "image_size": "full"}


def _subtree_text(node: dict[str, Any]) -> str:
    parts = [node.get("txt") or ""]
    for k in node.get("kids") or []:
        parts.append(_subtree_text(k))
    return " ".join(x for x in parts if x).strip()


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
    return out


def _w_icon_list(w: InferredWidget, ds: DesignSystem) -> dict[str, Any]:
    items = [k.get("txt") or "" for k in (w.node.get("kids") or []) if k.get("txt")]
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


def _w_divider(_w: InferredWidget, _ds: DesignSystem) -> dict[str, Any]:
    return {"style": "solid", "weight": {"unit": "px", "size": 1}}


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
            responsive: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
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
    elements: list[dict[str, Any]] = []
    if col.rows:
        for row in col.rows:
            elements.append(_row_as_inner_section(row, ds, ids, container_px, responsive))
    else:
        elements = [_widget(w, ds, ids, responsive) for w in col.widgets]
    return {
        "id": ids.next(f"col:{col.x}:{col.width_pct}"),
        "elType": "column",
        "settings": settings,
        "elements": elements,
    }


def _row_as_inner_section(row: InferredRow, ds: DesignSystem, ids: _IdGen,
                          container_px: int,
                          responsive: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {"gap": "default"}
    if row.structure:
        settings["structure"] = row.structure
    return {
        "id": ids.next(f"inner:{row.y}"),
        "elType": "section",
        "isInner": True,
        "settings": settings,
        "elements": [_column(c, ds, ids, container_px, responsive) for c in row.columns],
    }


def _section(section: InferredSection, ds: DesignSystem, ids: _IdGen,
             container_px: int,
             responsive: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {}
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
    if section.classes:
        settings["_css_classes"] = " ".join(section.classes[:4])
    if section.element_id:
        settings["_element_id"] = section.element_id

    # One row -> its columns ARE the section's columns. Many rows -> a single
    # full-width column of inner sections, which is Elementor's own idiom for
    # stacked bands inside one background.
    if len(section.rows) == 1:
        elements = [_column(c, ds, ids, container_px, responsive)
                    for c in section.rows[0].columns]
    else:
        inner = [_row_as_inner_section(r, ds, ids, container_px, responsive)
                 if len(r.columns) > 1 else
                 _column(r.columns[0], ds, ids, container_px, responsive)
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
               responsive: dict[str, dict[str, int]] | None = None) -> list[dict[str, Any]]:
    ids = _IdGen()
    return [_section(s, ds, ids, page.container_px, responsive) for s in page.sections]


def responsive_heading_sizes(captures: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    """{device: {heading text: font px}} from the tablet/mobile captures.

    Matched by TEXT because node identity does not survive across viewports - the
    prune keeps different wrappers at different widths - while a heading's text is
    the same page-fact everywhere it renders.
    """
    out: dict[str, dict[str, int]] = {}
    for device, root in captures.items():
        sizes: dict[str, int] = {}

        def walk(n: dict[str, Any], _sizes: dict[str, int] = sizes) -> None:
            if n.get("t") in ("h1", "h2", "h3", "h4", "h5", "h6") and n.get("txt"):
                px = _px((n.get("s") or {}).get("fontSize", ""))
                if px:
                    _sizes[n["txt"]] = px
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
