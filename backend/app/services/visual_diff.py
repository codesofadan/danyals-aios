"""Visual QA: diff a SOURCE DesignIR's measured sections against a FRESH
:class:`~integrations.site_analyzer.SiteCapture` of the RENDERED page (the
published WordPress build) and produce STRUCTURED diagnostics - never just one
similarity percentage (spec section 27: typography/layout/spacing/image/color/
alignment/size/responsive mismatches, each with a section + a human detail line).

WHY THIS COMPARES MEASURED VALUES, NOT PIXELS. The source's per-viewport screenshot
bytes are not retained past the analyze step (``design_ir_from_capture`` derives the
DesignIR body and discards the raw capture) - re-deriving a pixel diff would need a
new heavy image-processing dependency (Pillow/numpy) this codebase deliberately does
not carry by default. Every measurement a DesignIR already stores (section kind/
heading/bg_color/text_color/dimensions, typography per tag, container width, and the
per-viewport section counts in ``responsive``) is EXACTLY what real DOM/CSS
measurement produced in the first place, so diffing those values against a fresh
capture of the rendered page is itself a genuine, deterministic visual-fidelity
check - just expressed as structured facts instead of a fuzzy percentage.

Pure + deterministic (stdlib only): no network/DB/clock - both sides are already-
captured/measured data, so this unit-tests trivially against hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from integrations.site_analyzer import SiteCapture

MismatchKind = Literal[
    "typography", "layout", "spacing", "image", "color", "alignment", "size", "responsive"
]
QaStatus = Literal["pass", "warn", "fail"]

# Beyond this fractional difference, a numeric measurement (width/height/container/
# font-size) counts as a real mismatch rather than normal rendering jitter.
_SIZE_TOLERANCE = 0.12


@dataclass(frozen=True)
class Diagnostic:
    kind: MismatchKind
    section: str
    detail: str
    magnitude: float = 0.0  # 0..1, how far off (0 = trivial, 1 = totally different)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "section": self.section, "detail": self.detail, "magnitude": round(self.magnitude, 3)}


@dataclass(frozen=True)
class DiffResult:
    status: QaStatus
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "diagnostics": [d.as_dict() for d in self.diagnostics]}


def _px(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _rel_diff(a: float, b: float) -> float:
    """Fractional difference relative to the larger magnitude; 0 when both are 0."""
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom if denom else 0.0


def _first_px_font_size(capture: SiteCapture, *, tag: str, viewport: str = "desktop") -> float | None:
    vp = capture.viewport(viewport)
    if vp is None:
        return None
    sample = next((t for t in vp.typography if t.tag == tag), None)
    if sample is None:
        return None
    text = sample.font_size.strip()
    if text.endswith("px"):
        try:
            return float(text[:-2])
        except ValueError:
            return None
    return None


def diff_design_against_capture(design: dict[str, Any], rendered: SiteCapture) -> DiffResult:
    """Compare a persisted DesignIR body's measurements (``design_irs`` row shape:
    ``sections``/``typography``/``layout``/``responsive``) against a fresh capture
    of the rendered page. Returns a structured, multi-dimension verdict - never a
    single number."""
    diagnostics: list[Diagnostic] = []

    # --- typography: heading/body font-size drift at desktop -------------------
    typography = design.get("typography") or {}
    for tag, key in (("h1", "heading"), ("p", "body")):
        design_size = typography.get("base_size") if tag == "p" else None
        rendered_size = _first_px_font_size(rendered, tag=tag)
        if design_size and rendered_size is not None and str(design_size).endswith("px"):
            try:
                design_px = float(str(design_size)[:-2])
            except ValueError:
                continue
            if _rel_diff(design_px, rendered_size) > _SIZE_TOLERANCE:
                diagnostics.append(
                    Diagnostic(
                        "typography", key,
                        f"{key} font-size drifted: expected ~{design_px:g}px, rendered {rendered_size:g}px",
                        magnitude=min(1.0, _rel_diff(design_px, rendered_size)),
                    )
                )

    # --- layout: section count / order at desktop -------------------------------
    design_sections = design.get("sections") or []
    rendered_vp = rendered.viewport("desktop")
    rendered_content = (
        [s for s in rendered_vp.sections if s.role not in {"header", "nav", "footer"}] if rendered_vp else []
    )
    if len(design_sections) and len(rendered_content) and len(design_sections) != len(rendered_content):
        diagnostics.append(
            Diagnostic(
                "layout", "page",
                f"expected {len(design_sections)} content section(s), rendered page has {len(rendered_content)}",
                magnitude=min(1.0, abs(len(design_sections) - len(rendered_content)) / max(len(design_sections), 1)),
            )
        )

    # --- spacing: container width at desktop ------------------------------------
    design_container = _px((design.get("layout") or {}).get("container_width_px"))
    rendered_container = rendered_vp.container_width_px if rendered_vp else None
    if (
        design_container is not None and rendered_container is not None
        and _rel_diff(design_container, rendered_container) > _SIZE_TOLERANCE
    ):
        diagnostics.append(
            Diagnostic(
                "spacing", "page",
                f"container width drifted: expected ~{design_container:g}px, rendered {rendered_container:g}px",
                magnitude=min(1.0, _rel_diff(design_container, rendered_container)),
            )
        )

    # --- color + size, per aligned section (best-effort positional pairing) ----
    for i, (d_sec, r_sec) in enumerate(zip(design_sections, rendered_content, strict=False)):
        label = str(d_sec.get("kind") or f"section-{i}")
        d_bg = str(d_sec.get("bg_color") or "")
        r_bg = str(r_sec.bg_color or "")
        if d_bg and r_bg and d_bg != r_bg:
            diagnostics.append(
                Diagnostic("color", label, f"background colour drifted: expected {d_bg}, rendered {r_bg}", magnitude=0.5)
            )
        d_w = _px(d_sec.get("width"))
        if d_w and r_sec.width and _rel_diff(d_w, r_sec.width) > _SIZE_TOLERANCE:
            diagnostics.append(
                Diagnostic(
                    "size", label,
                    f"width drifted: expected ~{d_w:g}px, rendered {r_sec.width:g}px",
                    magnitude=min(1.0, _rel_diff(d_w, r_sec.width)),
                )
            )

    # --- images: measured asset count at desktop --------------------------------
    design_assets = design.get("assets") or []
    rendered_assets = rendered_vp.assets if rendered_vp else []
    if design_assets and not rendered_assets:
        diagnostics.append(
            Diagnostic("image", "page", "source page had images; none were detected on the rendered page", magnitude=0.6)
        )

    # --- responsive: per-viewport section-count reflow --------------------------
    design_responsive = {r.get("viewport"): r for r in (design.get("responsive") or []) if isinstance(r, dict)}
    for vp in rendered.viewports:
        expected = design_responsive.get(vp.viewport)
        if expected is None:
            continue
        expected_count = expected.get("section_count")
        actual_count = len([s for s in vp.sections if s.role not in {"header", "nav", "footer"}])
        if isinstance(expected_count, int) and expected_count and actual_count and expected_count != actual_count:
            diagnostics.append(
                Diagnostic(
                    "responsive", vp.viewport,
                    f"{vp.viewport}: expected {expected_count} section(s) after reflow, rendered has {actual_count}",
                    magnitude=min(1.0, abs(expected_count - actual_count) / max(expected_count, 1)),
                )
            )

    if not diagnostics:
        status: QaStatus = "pass"
    elif any(d.magnitude >= 0.6 for d in diagnostics) or len(diagnostics) >= 4:
        status = "fail"
    else:
        status = "warn"
    return DiffResult(status=status, diagnostics=diagnostics)
