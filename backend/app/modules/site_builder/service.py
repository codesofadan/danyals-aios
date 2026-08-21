"""The pure DesignIR builder: turn a measured :class:`SiteCapture` (real DOM/CSS,
``integrations.site_analyzer``) - or a chosen template - into a JSON-safe DesignIR
body ready to persist into ``design_irs``.

Pure + deterministic (stdlib only, no network/DB/clock/randomness) so it unit-tests
against a hand-built :class:`SiteCapture` fixture, exactly like
``app.services.site_design.build_profile`` builds a profile from parsed JSON. The
section ``kind``/``layout`` vocabulary is REUSED from ``app.services.page_blueprints``
(not reinvented) so a DesignIR-driven page can resolve through the existing
``resolve_blueprint`` / ``page_model`` / ``elementor`` renderers unchanged.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.modules.site_builder.schemas import slots_for_kind
from app.services.page_blueprints import LAYOUT_VARIANTS, get_template
from integrations.site_analyzer import SectionSnapshot, SiteCapture, TypographySample

# Heading-keyword -> section kind, in priority order (most specific first). Mirrors
# ``app.services.elementor._CHUNK_KEYWORDS`` so a measured section's heading text
# classifies into the SAME vocabulary a generated draft's ``<h2>`` would.
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("faq", ("faq", "frequently asked", "question")),
    ("testimonials", ("testimonial", "what clients say", "what customers", "reviews", "what our")),
    ("pricing", ("pricing", "price", "packages", "plans", "cost")),
    ("process", ("how it works", "how we work", "our process", "the process", "steps")),
    ("benefits", ("benefit", "why choose", "why work", "advantage", "why us")),
    ("features", ("features", "what's included", "what you get", "included", "what we offer")),
    ("team", ("meet the team", "our team", "leadership")),
    ("about", ("about",)),
    ("proof", ("proof", "results", "case stud", "evidence", "track record")),
    ("cta", ("get started", "get in touch", "next step", "ready to", "contact us", "book ")),
)
_DEFAULT_CONTENT_KIND = "intro"
_CHROME_ROLES = frozenset({"header", "nav", "footer"})


def _classify_kind(heading: str, *, is_first: bool) -> str:
    """The FIRST measured content block is always ``hero`` (mirrors
    ``page_blueprints``'s own invariant); the rest classify by heading keyword, else
    a generic ``intro`` body kind."""
    if is_first:
        return "hero"
    low = (heading or "").lower()
    for kind, kws in _KIND_KEYWORDS:
        if any(kw in low for kw in kws):
            return kind
    return _DEFAULT_CONTENT_KIND


def _classify_layout(section: SectionSnapshot, *, kind: str) -> str:
    """A best-effort layout GUESS from real measurements (child count + aspect
    ratio), constrained to the known ``LAYOUT_VARIANTS`` vocabulary so the renderer
    never receives an unknown variant."""
    if kind == "hero":
        return "split" if section.width > 0 and section.height > 0 and section.width / max(section.height, 1) > 1.6 else "centered"
    if kind == "faq":
        return "accordion"
    if kind in {"pricing"}:
        return "cards"
    if kind == "process":
        return "numbered-steps"
    if section.child_count >= 3:
        return "grid"
    return "stacked"


def _sections_from_capture(capture: SiteCapture, *, viewport: str = "desktop") -> list[dict[str, Any]]:
    vp = capture.viewport(viewport)
    if vp is None:
        return []
    content_sections = [s for s in vp.sections if s.role not in _CHROME_ROLES]
    out: list[dict[str, Any]] = []
    for i, s in enumerate(content_sections):
        kind = _classify_kind(s.heading, is_first=(i == 0))
        layout = _classify_layout(s, kind=kind)
        if layout not in LAYOUT_VARIANTS:
            layout = "stacked"
        out.append(
            {
                "kind": kind, "heading": s.heading, "layout": layout, "content": True,
                "slots": slots_for_kind(kind), "text_sample": s.text_sample,
                "bg_color": s.bg_color, "text_color": s.text_color,
            }
        )
    return out


def _mode_color(values: list[str]) -> str:
    cleaned = [v for v in values if v and v not in {"rgba(0, 0, 0, 0)", "transparent"}]
    if not cleaned:
        return ""
    return Counter(cleaned).most_common(1)[0][0]


def _palette_from_capture(capture: SiteCapture) -> dict[str, str]:
    vp = capture.viewport("desktop")
    if vp is None:
        return {}
    bg = _mode_color([s.bg_color for s in vp.sections])
    text = _mode_color([s.text_color for s in vp.sections])
    heading_color = next((t.color for t in vp.typography if t.tag == "h1" and t.color), "")
    accent = next((t.color for t in vp.typography if t.tag in {"a", "button"} and t.color), "")
    palette: dict[str, str] = {}
    if bg:
        palette["background"] = bg
    if text:
        palette["text"] = text
    if heading_color:
        palette["primary"] = heading_color
    if accent:
        palette["accent"] = accent
    return palette


def _typography_from_capture(capture: SiteCapture) -> dict[str, str]:
    vp = capture.viewport("desktop")
    if vp is None:
        return {}
    by_tag: dict[str, TypographySample] = {t.tag: t for t in vp.typography}
    out: dict[str, str] = {}
    heading = by_tag.get("h1") or by_tag.get("h2")
    body = by_tag.get("p")
    if heading and heading.font_family:
        out["heading_font"] = heading.font_family
    if body:
        if body.font_family:
            out["body_font"] = body.font_family
        if body.font_size:
            out["base_size"] = body.font_size
    return out


def _responsive_from_capture(capture: SiteCapture) -> list[dict[str, Any]]:
    """What ACTUALLY changes at each measured breakpoint - observed section-count
    reflow + font scaling, not a desktop shrink."""
    out: list[dict[str, Any]] = []
    for vp in capture.viewports:
        content_sections = [s for s in vp.sections if s.role not in _CHROME_ROLES]
        body_font = next((t.font_size for t in vp.typography if t.tag == "p"), "")
        out.append(
            {
                "viewport": vp.viewport, "width": vp.width, "container_width_px": vp.container_width_px,
                "base_font_size": body_font, "section_count": len(content_sections),
            }
        )
    return out


def _assets_from_capture(capture: SiteCapture, *, limit: int = 20) -> list[dict[str, Any]]:
    vp = capture.viewport("desktop")
    if vp is None:
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in vp.assets:
        if a.url in seen:
            continue
        seen.add(a.url)
        out.append({"url": a.url, "alt": a.alt, "width": a.width, "height": a.height, "kind": a.kind})
        if len(out) >= limit:
            break
    return out


def design_ir_from_capture(
    capture: SiteCapture, *, source_type: str, source_url: str, industry: str = "", page_type: str = ""
) -> dict[str, Any]:
    """Build a JSON-safe DesignIR body (matching ``design_irs``'s jsonb columns)
    from a REAL, measured :class:`SiteCapture`. ``source_type`` is
    ``existing_site`` (reconstruct as-is) or ``reference_site`` (layout borrowed,
    content NOT - the caller is responsible for stripping/never persisting the
    measured ``text_sample``/proprietary copy downstream when reference-mode)."""
    sections = _sections_from_capture(capture)
    palette = _palette_from_capture(capture)
    typography = _typography_from_capture(capture)
    desktop = capture.viewport("desktop")
    return {
        "source_type": source_type,
        "source_url": source_url,
        "industry": industry,
        "page_type": page_type,
        "palette": palette,
        "typography": typography,
        "layout": {
            "container_width_px": desktop.container_width_px if desktop else None,
            "section_order": [s["kind"] for s in sections],
        },
        "responsive": _responsive_from_capture(capture),
        "components": {},
        "assets": _assets_from_capture(capture),
        "sections": sections,
        "supported_editors": ["elementor", "gutenberg", "hybrid"],
        "notes": f"measured from {len(capture.viewports)} viewport(s); title={capture.title!r}",
        "wireframe_html": "",
    }


# --------------------------------------------------------------------------- #
# The TEMPLATE path: a DesignIR built from one of the 7 existing page_blueprints
# templates (reused, not reinvented) with a classic default palette.
# --------------------------------------------------------------------------- #
_CLASSIC_PALETTE: dict[str, str] = {
    "primary": "#0f172a", "secondary": "#475569", "background": "#ffffff",
    "text": "#1e293b", "accent": "#2563eb",
}
_CLASSIC_TYPOGRAPHY: dict[str, str] = {
    "heading_font": "Sora, system-ui, sans-serif", "body_font": "Inter, system-ui, sans-serif", "base_size": "17px",
}


def design_ir_from_template(template_name: str, *, industry: str = "", page_type: str = "") -> dict[str, Any] | None:
    """A DesignIR seeded from a named ``page_blueprints`` template, or ``None`` for
    an unknown template key."""
    blueprint = get_template(template_name)
    if blueprint is None:
        return None
    sections = [
        {
            "kind": s.kind, "heading": s.heading, "layout": s.layout, "content": s.content,
            "slots": slots_for_kind(s.kind), "text_sample": "", "bg_color": "", "text_color": "",
        }
        for s in blueprint.sections
    ]
    return {
        "source_type": "template",
        "source_url": "",
        "industry": industry,
        "page_type": page_type or blueprint.page_type,
        "design_style": template_name,
        "palette": dict(_CLASSIC_PALETTE),
        "typography": dict(_CLASSIC_TYPOGRAPHY),
        "layout": {"container_width_px": 1160.0, "section_order": blueprint.section_order},
        "responsive": [],
        "components": {"button_style": "solid rounded", "card_style": "soft shadow", "spacing_scale": "comfortable"},
        "assets": [],
        "sections": sections,
        "supported_editors": ["elementor", "gutenberg", "hybrid"],
        "notes": f"seeded from template={template_name!r} ({blueprint.notes})",
        "wireframe_html": "",
    }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").lower()).strip("-") or "page"


# --------------------------------------------------------------------------- #
# Template recommendation (spec section 35): rank an already-fetched catalog by
# how well each entry matches the requested industry + page type - pure ranking,
# no DB access (the repo does the fetch; this just orders what it returned).
# --------------------------------------------------------------------------- #
def _match_tier(row: dict[str, Any], *, industry: str, page_type: str) -> int:
    """Lower is better. Exact industry+pageType match wins; a generic (industry='')
    entry for the right page type is next; a same-category-only match trails; an
    unrelated entry sorts last but is never dropped (the gallery still shows
    everything, just ordered)."""
    row_industry = str(row.get("industry") or "")
    row_page_type = str(row.get("page_type") or "")
    if industry and row_industry == industry and page_type and row_page_type == page_type:
        return 0
    if page_type and row_page_type == page_type and not row_industry:
        return 1
    if page_type and row_page_type == page_type:
        return 2
    if industry and row_industry == industry:
        return 3
    return 4


def rank_templates(rows: list[dict[str, Any]], *, industry: str = "", page_type: str = "") -> list[dict[str, Any]]:
    """Order a fetched template catalog by relevance to ``industry``/``page_type``,
    best match first; ties break by rating (highest first, unrated last) then name."""
    def _key(row: dict[str, Any]) -> tuple[int, float, str]:
        rating = row.get("rating")
        rating_key = -float(rating) if rating is not None else 0.0
        return (_match_tier(row, industry=industry, page_type=page_type), rating_key, str(row.get("name") or ""))

    return sorted(rows, key=_key)


# --------------------------------------------------------------------------- #
# DesignIR -> PageModel (Phase 6): so a resolved DesignIR can render through the
# EXISTING html/Elementor/Gutenberg renderers unchanged - one editable model, three
# renderers, exactly like a content job's PageModel already works.
# --------------------------------------------------------------------------- #
# source_type carries REAL text into the published page ONLY for existing_site
# (reconstructing the client's OWN site) and template/manual (no proprietary copy
# involved). reference_site is explicitly LAYOUT-ONLY (spec section 5: "do not
# blindly copy copyrighted text... from the reference site") - its measured
# text_sample is a REFERENCE's copy, not the client's, so content sections are left
# BLANK (hidden placeholders the operator fills with the client's own words) even
# though the section STRUCTURE (kind/layout/order) is still mirrored.
_COPY_ALLOWED_SOURCES: frozenset[str] = frozenset({"existing_site", "template", "manual"})
_GRID_KINDS: frozenset[str] = frozenset({"benefits", "features", "services", "usp"})


def _section_data_for_kind(kind: str, text_sample: str) -> dict[str, Any]:
    """A best-effort ``Section.data`` payload for a kind carrying only a flat
    ``heading``/``text_sample`` (a DesignIR section has no structured sub-items like
    FAQ pairs or testimonial quotes - only real AI/human authoring produces those).
    A kind that needs structured children (faq/testimonials/process/grid) gets an
    EMPTY payload here, so the caller marks it invisible rather than fabricating fake
    Q&A pairs or quotes; ``cta``/``prose``/``hero`` still show real measured text."""
    if kind == "hero":
        return {"subhead": text_sample, "buttons": []}
    if kind == "cta":
        return {"text": text_sample, "button": {"label": "Get in touch", "url": "#"}}
    if kind in {"faq", "testimonials", "process"} or kind in _GRID_KINDS:
        return {}
    return {"html": f"<p>{text_sample}</p>" if text_sample else ""}


def design_ir_to_page_model(design: dict[str, Any], *, title: str) -> dict[str, Any]:
    """Build a ``PageModel.to_dict()``-shaped dict from a persisted DesignIR row, so
    it renders through the EXISTING ``page_model.model_to_html`` /
    ``elementor.model_to_elementor`` / ``gutenberg.model_to_gutenberg`` unchanged."""
    source_type = str(design.get("source_type") or "")
    copy_allowed = source_type in _COPY_ALLOWED_SOURCES
    sections: list[dict[str, Any]] = []
    for i, s in enumerate(design.get("sections") or []):
        if not isinstance(s, dict):
            continue
        kind = str(s.get("kind") or "prose")
        text_sample = str(s.get("text_sample") or "") if copy_allowed else ""
        data = _section_data_for_kind(kind, text_sample)
        has_content = bool(data.get("html") or data.get("subhead") or data.get("text") or kind == "hero")
        sections.append(
            {
                "id": f"s{i}", "kind": kind, "layout": str(s.get("layout") or "stacked"),
                "heading": str(s.get("heading") or ""), "visible": has_content,
                "data": data, "images": [],
            }
        )
    return {
        "title": title,
        "design": {
            "palette": design.get("palette") or {}, "typography": design.get("typography") or {},
            "components": design.get("components") or {},
        },
        "sections": sections,
    }


def page_title_for_design(design: dict[str, Any]) -> str:
    """A reasonable page title: the hero's heading, else the page_type/industry,
    else a generic fallback - never blank (WordPress requires a title)."""
    for s in design.get("sections") or []:
        if isinstance(s, dict) and s.get("kind") == "hero" and str(s.get("heading") or "").strip():
            return str(s["heading"]).strip()
    label = str(design.get("page_type") or design.get("industry") or "").replace("_", " ").strip()
    return label.title() if label else "New Page"
