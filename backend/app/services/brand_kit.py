"""The brand kit - one client's look, measured once and kept (P6.1).

WHY A KIT AT ALL. The owner's ask is fifty-plus pages that "look like the same developer
built them". Nothing in v1 persists a client's look: `site_analyzer` measures it,
`site_design` interprets it, and both results live only inside the job that produced
them. Page 2 re-derives everything page 1 already knew, and any drift between the two
derivations lands on the client's live site as two pages that do not match.

MEASUREMENT BEATS INTERPRETATION, AND THAT IS THE WHOLE MERGE RULE.

`site_analyzer` runs real `getComputedStyle` at three viewports. What it returns is not
an opinion: the heading font IS whatever the browser resolved, the container IS however
many pixels wide. `site_design` asks a model to look at the page and describe it, which
is genuinely better at things no measurement captures - is the hero centred or split,
does the CTA read as a banner or an inline strip, what is the section ORDER for.

So they are not blended. Each side owns what it can actually know:

    palette, typography, spacing   <- measured   (getComputedStyle, 3 viewports)
    blueprint, components, layout  <- interpreted (the model's reading)

Where a measurement exists it WINS, every time, with no confidence weighting. A model
that says the heading font is Inter when the browser resolved Georgia is simply wrong,
and averaging the two produces a page that matches neither.

VERSIONED, because client sites change. A page published under kit v1 has to stay
explainable after the client's redesign, so a new capture creates a new version and
deactivates the old rather than overwriting it. `brand_kits` has a partial unique index
on `(client_id) where active`, so "the current kit" is a database guarantee rather than
a convention this module has to remember.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Tags whose computed style defines the heading face. Ordered: an h1 beats an h2 when
# a page styles them differently, because the h1 is the page's own voice.
_HEADING_TAGS: tuple[str, ...] = ("h1", "h2", "h3")
_BODY_TAGS: tuple[str, ...] = ("p", "li", "body", "div")

# Colours that carry no brand information. A palette built from these describes the
# absence of styling rather than a brand, and picking an "accent" out of them produces
# a confident wrong answer.
_NEUTRAL = frozenset({
    "#000000", "#000", "#ffffff", "#fff", "transparent", "rgba(0, 0, 0, 0)", "",
    "inherit", "initial", "currentcolor", "none",
})

# The `brand_asset_kind` enum in migration 0089. `site_analyzer` speaks a DIFFERENT
# vocabulary - Literal["logo", "image"] - and the two share no import, so nothing made
# them agree. Measured against a real Postgres: recording a captured image raised
# `invalid input value for enum brand_asset_kind: "image"`, at INSERT time, in a worker.
#
# Translated here rather than at the database, because this is the module that knows
# what the analyzer meant. An unmapped kind raises with both vocabularies named, rather
# than reaching Postgres and failing as a type error nobody can place.
BRAND_ASSET_KINDS: frozenset[str] = frozenset({"logo", "photo", "icon", "favicon"})

_ANALYZER_KIND_TO_ASSET_KIND: dict[str, str] = {
    "logo": "logo",
    "image": "photo",
}


def asset_kind_for(analyzer_kind: str) -> str:
    """Map a `site_analyzer` asset kind onto the `brand_asset_kind` enum."""
    mapped = _ANALYZER_KIND_TO_ASSET_KIND.get((analyzer_kind or "").strip().lower())
    if mapped is None:
        raise ValueError(
            f"no brand_asset_kind for analyzer kind {analyzer_kind!r}; "
            f"the enum accepts {sorted(BRAND_ASSET_KINDS)}"
        )
    return mapped


_HEX_RE = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$", re.I)
_RGB_RE = re.compile(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", re.I)


@dataclass(frozen=True)
class BrandKit:
    """One client's resolved look, with every field's provenance recorded."""

    source_url: str = ""
    palette: dict[str, str] = field(default_factory=dict)
    typography: dict[str, str] = field(default_factory=dict)
    spacing: dict[str, Any] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)
    blueprint: list[dict[str, Any]] = field(default_factory=list)
    assets: tuple[str, ...] = ()
    # field name -> "measured" | "interpreted" | "default". Not decoration: it is what
    # lets an operator answer "why is this page's heading font Georgia" a year later.
    provenance: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def measured_fields(self) -> int:
        return sum(1 for v in self.provenance.values() if v == "measured")

    @property
    def is_grounded(self) -> bool:
        """True when the kit rests on real measurement rather than model guesswork.

        A kit that is entirely interpreted is still usable - it is better than nothing
        for a site we could not render - but a full-site build should know it is
        working from a description rather than from the page itself.
        """
        return self.measured_fields >= 3


def normalise_colour(value: str) -> str:
    """A comparable lowercase hex, or "" for anything that carries no brand signal."""
    raw = (value or "").strip().lower()
    if not raw or raw in _NEUTRAL:
        return ""
    if _HEX_RE.match(raw):
        if len(raw) == 4:  # #abc -> #aabbcc, so two spellings of one colour agree
            return "#" + "".join(c * 2 for c in raw[1:])
        return raw
    m = _RGB_RE.match(raw)
    if m:
        r, g, b = (min(255, int(x)) for x in m.groups())
        hexed = f"#{r:02x}{g:02x}{b:02x}"
        return "" if hexed in _NEUTRAL else hexed
    return ""


def _dominant(values: list[str]) -> str:
    """The most common non-neutral colour, ties broken by first appearance.

    Deterministic on purpose: two runs over the same capture must produce the same
    kit, or "the same developer built them" stops being true across a rebuild.
    """
    ordered = [c for c in (normalise_colour(v) for v in values) if c]
    if not ordered:
        return ""
    counts = Counter(ordered)
    best = max(counts.values())
    for colour in ordered:  # first-appearance tiebreak
        if counts[colour] == best:
            return colour
    return ""


def _first_font(samples: list[dict[str, Any]], tags: tuple[str, ...]) -> tuple[str, str]:
    """(font_family, font_size) for the first tag in ``tags`` that was measured."""
    by_tag: dict[str, dict[str, Any]] = {}
    for s in samples:
        tag = str(s.get("tag") or "").lower()
        if tag and tag not in by_tag:
            by_tag[tag] = s
    for tag in tags:
        sample = by_tag.get(tag)
        if sample and str(sample.get("font_family") or "").strip():
            return (
                str(sample["font_family"]).strip(),
                str(sample.get("font_size") or "").strip(),
            )
    return "", ""


def from_measurements(capture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Palette, typography and spacing from a `SiteCapture`, plus their provenance.

    Only the DESKTOP viewport feeds typography and container width. Mobile resolves a
    different computed size for the same element, so mixing viewports produces a base
    size the site never actually renders at.
    """
    viewports = capture.get("viewports") or []
    desktop = next(
        (v for v in viewports if str(v.get("viewport")) == "desktop"),
        viewports[0] if viewports else {},
    )
    sections = desktop.get("sections") or []
    typography_samples = desktop.get("typography") or []

    provenance: dict[str, str] = {}
    palette: dict[str, str] = {}
    background = _dominant([str(s.get("bg_color") or "") for s in sections])
    text = _dominant([str(s.get("text_color") or "") for s in sections])
    heading_colour = _dominant([
        str(s.get("color") or "") for s in typography_samples
        if str(s.get("tag") or "").lower() in _HEADING_TAGS
    ])
    for key, value in (("background", background), ("text", text), ("primary", heading_colour)):
        if value:
            palette[key] = value
            provenance[f"palette.{key}"] = "measured"

    typography: dict[str, str] = {}
    heading_font, _ = _first_font(typography_samples, _HEADING_TAGS)
    body_font, body_size = _first_font(typography_samples, _BODY_TAGS)
    for key, value in (
        ("heading_font", heading_font), ("body_font", body_font), ("base_size", body_size)
    ):
        if value:
            typography[key] = value
            provenance[f"typography.{key}"] = "measured"

    spacing: dict[str, Any] = {}
    container = desktop.get("container_width_px")
    if isinstance(container, (int, float)) and container > 0:
        spacing["container_width"] = f"{int(container)}px"
        provenance["spacing.container_width"] = "measured"

    return (
        {"palette": palette, "typography": typography, "spacing": spacing},
        provenance,
    )


def merge(
    *,
    source_url: str = "",
    capture: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> BrandKit:
    """Build a kit: measurement where it exists, interpretation to fill the rest.

    Either input may be absent. A capture-only kit has no blueprint (nothing read the
    page's intent); a profile-only kit is honestly marked interpreted throughout and
    `is_grounded` reports False.
    """
    notes: list[str] = []
    measured, provenance = (
        from_measurements(capture) if capture else ({"palette": {}, "typography": {}, "spacing": {}}, {})
    )
    palette = dict(measured["palette"])
    typography = dict(measured["typography"])
    spacing = dict(measured["spacing"])

    profile = profile or {}
    if not capture:
        notes.append(
            "no browser capture: every value here is a model's reading of the page, "
            "not a measurement of it"
        )

    # Interpretation fills only what measurement did NOT establish. Never overwrites:
    # a model that says Inter when the browser resolved Georgia is wrong, not a second
    # opinion to average against.
    for section, fields in (
        ("palette", ("primary", "secondary", "background", "text", "accent")),
        ("typography", ("heading_font", "body_font", "base_size")),
    ):
        target = palette if section == "palette" else typography
        source = profile.get(section) or {}
        for name in fields:
            if name in target:
                continue
            value = str(source.get(name) or "").strip()
            if section == "palette":
                value = normalise_colour(value)
            if value:
                target[name] = value
                provenance[f"{section}.{name}"] = "interpreted"

    layout = profile.get("layout") or {}
    if "container_width" not in spacing:
        width = str(layout.get("container_width") or "").strip()
        if width:
            spacing["container_width"] = width
            provenance["spacing.container_width"] = "interpreted"

    components = dict(profile.get("components") or {})
    for name in components:
        provenance[f"components.{name}"] = "interpreted"
    for name in ("hero_style", "cta_style"):
        value = str(layout.get(name) or "").strip()
        if value:
            components[name] = value
            provenance[f"components.{name}"] = "interpreted"

    blueprint = [dict(b) for b in (layout.get("blueprint") or []) if isinstance(b, dict)]
    if blueprint:
        provenance["blueprint"] = "interpreted"

    assets = tuple(_asset_urls(capture)) if capture else ()
    if assets:
        notes.append(
            f"{len(assets)} asset URLs captured; they are still remote until re-hosted"
        )

    kit = BrandKit(
        source_url=source_url or str((capture or {}).get("url") or ""),
        palette=palette, typography=typography, spacing=spacing,
        components=components, blueprint=blueprint, assets=assets,
        provenance=provenance, notes=tuple(notes),
    )
    if not kit.is_grounded and capture:
        notes.append(
            "the capture yielded fewer than three measured fields; treat this kit as "
            "a description rather than a measurement"
        )
        kit = BrandKit(**{**kit.__dict__, "notes": tuple(notes)})
    return kit


def _asset_urls(capture: dict[str, Any]) -> list[str]:
    """Every distinct asset URL across viewports, logos first, in document order.

    `site_analyzer` captures these and v1 threw them away, which is why every page
    generated a stock image for a client whose own photograph was already on the page.
    """
    seen: set[str] = set()
    logos: list[str] = []
    images: list[str] = []
    for viewport in capture.get("viewports") or []:
        for asset in viewport.get("assets") or []:
            url = str(asset.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            (logos if str(asset.get("kind")) == "logo" else images).append(url)
    return [*logos, *images]
