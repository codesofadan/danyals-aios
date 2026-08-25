"""Recover a site's design system from what it actually renders (replication stage 2).

THE BRANDING IS THE POINT. An owner pointing at a site wants its palette, its type and
its shape language carried onto every new page. `site_design.py` asks a model to look at
a screenshot and describe those; this reads them off the rendered page.

TWO SOURCES, AND ONE BEATS THE OTHER.

  1. DECLARED. If the author wrote CSS custom properties, those ARE the design system -
     already named, already deduplicated, already the author's own compression of their
     intent. `--oh-brass: #A16207` is worth more than any clustering of ours, because it
     carries a NAME.
  2. DERIVED. Otherwise (and for any role the declarations do not cover) cluster the
     computed styles the browser resolved.

Validated on a real page: derived-only extraction recovered #F9FAFB, #E5E7EB, #111827,
#4B5563, #6B7280 and #A16207 - each one matching a token the author had declared
(--oh-shell, --oh-hair, --oh-charcoal, --oh-body, --oh-muted, --oh-brass) EXACTLY. So
the derivation is trustworthy where declarations are absent, which is the case for
every hand-coded site that does not use custom properties.

PROVENANCE IS RECORDED PER VALUE, following `brand_kit.py`'s rule verbatim: a measured
value beats an inferred one and the kit says which it was. A design system nobody can
account for six months later is a liability, not an asset.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Fonts that are icon sets, not typography. Elementor ships `eicons`; capturing it as
# the body face would set every paragraph in an icon font.
_ICON_FONTS = frozenset({"eicons", "font awesome", "fontawesome", "dashicons",
                         "material icons", "ionicons", "feather"})

# Colours that carry no brand signal.
_NEUTRAL_RGB = frozenset({"rgba(0, 0, 0, 0)", "transparent", ""})

# A node must cover at least this many square pixels to speak for the page background.
_LARGE_AREA = 50_000

# A brand accent is unmistakably chromatic. 0.30 sits above slate-greys like #374151
# (0.19) and well below a real brand colour like #A16207 (0.92).
_MIN_ACCENT_SATURATION = 0.30
# ...and it has to be used deliberately, not appear once by accident.
_MIN_ACCENT_USES = 3

_RGB_RE = re.compile(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)")
_PX_RE = re.compile(r"^(-?[\d.]+)px$")


def to_hex(value: str) -> str:
    """A comparable `#rrggbb`, or "" for anything transparent or unparseable."""
    raw = (value or "").strip().lower()
    if not raw or raw in _NEUTRAL_RGB:
        return ""
    if raw.startswith("#"):
        if len(raw) == 4:
            return "#" + "".join(c * 2 for c in raw[1:])
        return raw if len(raw) == 7 else ""
    m = _RGB_RE.match(raw)
    if not m:
        return ""
    if m.group(4) is not None and float(m.group(4)) < 0.05:
        return ""  # effectively transparent
    r, g, b = (min(255, int(x)) for x in m.groups()[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(hex_colour: str) -> float:
    """Perceived lightness 0..1. Used to tell a SURFACE from a BORDER.

    Counting occurrences alone gets this wrong: on the reference page the hairline
    (#E5E7EB) appears more often than the surface (#F9FAFB), so frequency ranking
    labelled the border as the surface and vice versa. A surface is the tone NEAREST
    the page background; a border is the one that steps away from it.
    """
    h = (hex_colour or "").lstrip("#")
    if len(h) != 6:
        return 0.0
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(hex_colour: str) -> float:
    """HSL saturation 0..1. An ACCENT is chromatic; greys and white are not.

    Without this the accent resolved to #ffffff, because link text on a dark section is
    white and white was the modal link colour. White is never a brand accent.
    """
    h = (hex_colour or "").lstrip("#")
    if len(h) != 6:
        return 0.0
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hi, lo = max(r, g, b), min(r, g, b)
    if hi == lo:
        return 0.0
    d, ln = hi - lo, (hi + lo) / 2
    return d / (2 - hi - lo) if ln > 0.5 else d / (hi + lo)


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance, with the sRGB gamma actually applied.

    Not the same as `luminance()` above. Using raw channel values in a contrast ratio
    understates dark colours badly: it scored #111827 on white at 7.4:1 (actually 17.4) and
    #4B5563 at 2.8:1 (actually 7.5). The second error mattered - a >= 3.0 readability filter
    was discarding the page's actual body colour as "unreadable" and falling through to
    a different grey.
    """
    h = (hex_colour or "").lstrip("#")
    if len(h) != 6:
        return 0.0
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours (1.0 .. 21.0)."""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _px(value: str) -> float | None:
    m = _PX_RE.match((value or "").strip())
    return float(m.group(1)) if m else None


def _family(value: str) -> str:
    """The first real family in a stack, quotes stripped, icon fonts rejected."""
    first = (value or "").split(",")[0].strip().strip('"').strip("'")
    return "" if first.lower() in _ICON_FONTS else first


@dataclass(frozen=True)
class DesignSystem:
    """One site's resolved design language."""

    palette: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, str] = field(default_factory=dict)
    type_scale: tuple[int, ...] = ()
    radius_scale: tuple[int, ...] = ()
    spacing_scale: tuple[int, ...] = ()
    container_px: int = 0
    declared_tokens: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def declared_count(self) -> int:
        return sum(1 for v in self.provenance.values() if v == "declared")

    @property
    def is_grounded(self) -> bool:
        """True when the system rests on real measurement, not on defaults."""
        return len(self.palette) >= 3 and bool(self.fonts.get("body"))


def _scale(values: list[float], *, limit: int = 8) -> tuple[int, ...]:
    """The distinct steps of a scale, ascending.

    Values within 1px are one step - a browser resolving 11.9994px and 12px is
    describing the same design decision, and treating them as two loses the scale.
    """
    out: list[int] = []
    for v in sorted({round(x) for x in values if x and x > 0}):
        if not out or v - out[-1] > 1:
            out.append(int(v))
    return tuple(out[:limit])


def _modal(counter: Counter[str]) -> str:
    return counter.most_common(1)[0][0] if counter else ""


def extract(
    nodes: list[dict[str, Any]],
    *,
    css_vars: dict[str, str] | None = None,
    container_px: int = 0,
) -> DesignSystem:
    """Recover the design system from captured nodes plus any declared tokens.

    ``nodes`` are raw capture dicts (`{t, box, s, txt, ...}`) so this stays usable from
    a fixture with no browser. Total: never raises.
    """
    css_vars = css_vars or {}
    palette: dict[str, str] = {}
    provenance: dict[str, str] = {}
    notes: list[str] = []

    # --- 1. declared tokens win, and keep their names ----------------------- #
    own = {
        k: v for k, v in css_vars.items()
        # Elementor's and the theme's own variables describe THEIR defaults, not this
        # site's design decisions.
        if not k.startswith(("--e-global", "--elementor", "--wp", "--ast", "--kit"))
    }
    declared_colours = {k: to_hex(v) for k, v in own.items() if to_hex(v)}

    # Colours that ARE a framework token's value are the THEME speaking, not the
    # author. Measured: a deeper capture surfaced #046bd2 on 17 unstyled links -
    # saturation 0.96, outscoring the real brass - and it is literally
    # `--ast-global-color-0`, Astra's default, confirmed by three separate framework
    # variables. Unless the author also declared it themselves, it cannot be the
    # brand accent.
    framework_colours = {
        to_hex(v)
        for k, v in css_vars.items()
        if k.startswith(("--e-global", "--elementor", "--wp", "--ast", "--kit"))
        and to_hex(v)
    } - set(declared_colours.values())

    # --- 2. derive from what the browser actually resolved ------------------ #
    bg_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    head_counts: Counter[str] = Counter()
    link_counts: Counter[str] = Counter()
    body_fonts: Counter[str] = Counter()
    head_fonts: Counter[str] = Counter()
    radii: list[float] = []
    pads: list[float] = []
    head_sizes: list[float] = []
    body_sizes: list[float] = []

    for node in nodes:
        style = node.get("s") or {}
        if not style:
            continue
        tag = str(node.get("t") or "")
        box = node.get("box") or [0, 0, 0, 0]
        area = (box[2] or 0) * (box[3] or 0)
        text = str(node.get("txt") or "")
        heading = tag in ("h1", "h2", "h3", "h4")

        bg = to_hex(style.get("backgroundColor", ""))
        if bg and area >= _LARGE_AREA:
            bg_counts[bg] += 1
        colour = to_hex(style.get("color", ""))
        if colour and text:
            (head_counts if heading else text_counts)[colour] += 1
        if colour and tag in ("a", "button"):
            link_counts[colour] += 1

        fam = _family(style.get("fontFamily", ""))
        if fam and text:
            (head_fonts if heading else body_fonts)[fam] += 1

        r = _px(style.get("borderRadius", ""))
        if r:
            radii.append(r)
        p = _px(style.get("paddingTop", ""))
        if p:
            pads.append(p)
        size = _px(style.get("fontSize", ""))
        if size and text:
            (head_sizes if heading else body_sizes).append(size)

    # --- 3. assign roles, declared beating derived -------------------------- #
    def assign(role: str, derived: str, *names: str) -> None:
        for name in names:
            for key, hexed in declared_colours.items():
                if name in key:
                    palette[role] = hexed
                    provenance[f"palette.{role}"] = "declared"
                    return
        if derived:
            palette[role] = derived
            provenance[f"palette.{role}"] = "derived"

    ordered_bg = [c for c, _ in bg_counts.most_common()]
    page_bg = ordered_bg[0] if ordered_bg else ""
    assign("background", page_bg, "white", "bg", "background")
    resolved_bg = palette.get("background", page_bg)

    # Surface vs border by LUMINANCE DISTANCE, not by frequency. The nearest tone to the
    # background is a surface (a subtly tinted band); the one that steps further away is
    # a hairline. Ranking by count had these exactly backwards.
    others = [c for c in ordered_bg[1:] if c != resolved_bg]
    others.sort(key=lambda c: abs(luminance(c) - luminance(resolved_bg)))
    assign("surface", others[0] if others else "", "shell", "surface", "strip")
    assign("border", others[1] if len(others) > 1 else "", "hair", "border", "divider")

    assign("heading", _modal(head_counts), "charcoal", "ink", "heading", "title")

    # Body text must be READABLE ON THE PAGE BACKGROUND. Taking the modal colour across
    # every text node picked up the footer's light-on-dark grey, which is a correct
    # measurement of the wrong thing.
    readable = Counter({
        c: n for c, n in text_counts.items()
        if not resolved_bg or contrast(c, resolved_bg) >= 3.0
    })
    assign("text", _modal(readable) or _modal(text_counts), "body", "text")

    # Muted: readable, but lower contrast than the body colour.
    body_hex = palette.get("text", "")
    if body_hex and resolved_bg:
        dimmer = Counter({
            c: n for c, n in readable.items()
            if contrast(c, resolved_bg) < contrast(body_hex, resolved_bg) and c != body_hex
        })
        assign("muted", _modal(dimmer), "muted", "subtle", "slate")
    else:
        assign("muted", "", "muted", "subtle", "slate")

    # An accent is CHROMATIC, and it is picked by SATURATION rather than by frequency.
    #
    # Two failures got us here, both measured. Ranking links by count returned #ffffff,
    # because white link text on a dark band is the commonest link colour and white is
    # never a brand accent. Filtering at saturation >= 0.15 then returned #374151 - a
    # slate that clears a low bar on a technicality while the page's actual brass
    # (#A16207, saturation 0.92) sat further down the list.
    #
    # A brand accent is the most CHROMATIC colour the page uses with any regularity, not
    # the most frequent one: it appears on a few buttons and links, by design.
    candidates = Counter(link_counts) + Counter(text_counts)
    chromatic = [
        c for c, n in candidates.items()
        if saturation(c) >= _MIN_ACCENT_SATURATION and n >= _MIN_ACCENT_USES
        and c not in framework_colours
    ]
    chromatic.sort(key=lambda c: (-saturation(c), -candidates[c]))
    assign("accent", chromatic[0] if chromatic else "",
           "brass", "gold", "accent", "primary", "brand")

    fonts: dict[str, str] = {}
    hf, bf = _modal(head_fonts), _modal(body_fonts)
    if hf:
        fonts["heading"] = hf
        provenance["fonts.heading"] = "derived"
    if bf:
        fonts["body"] = bf
        provenance["fonts.body"] = "derived"
    if not fonts:
        notes.append("no non-icon font family was resolvable from the captured text")

    if not palette:
        notes.append("no palette could be resolved; the capture may be empty")
    if declared_colours:
        notes.append(
            f"{len(declared_colours)} colour tokens were DECLARED by the source and "
            "used in preference to clustering"
        )

    return DesignSystem(
        palette=palette,
        fonts=fonts,
        type_scale=_scale([*head_sizes, *body_sizes]),
        radius_scale=_scale([r for r in radii if r < 100]),  # 9999px is a pill, not a step
        spacing_scale=_scale(pads),
        container_px=container_px,
        declared_tokens=own,
        provenance=provenance,
        notes=tuple(notes),
    )
