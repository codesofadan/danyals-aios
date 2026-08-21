"""Site-design EXTRACTOR: gather a target site's EXISTING design so a new page can
be built to MATCH it BEFORE it is published to the client's WordPress.

The user's requirement, in three moves: (1) GATHER the target site's existing
design/layout/UI, (2) build the new page's structure to MATCH it, (3) fill in the
content. This module is the FOUNDATION of move (1) + the seam for move (2): it turns
the RENDERED site - a Firecrawl SCREENSHOT (what the site actually looks like) plus
its rendered text - into a bounded, strict :class:`SiteDesignProfile` (palette /
typography / layout+section-order / component styles + a self-contained
``wireframe_html`` preview) that the content job carries in its
``source_pack["design_profile"]`` and the publish path uses to wrap the generated
body in ordered ``<section class="aios-<name>">`` blocks.

WHY VISION: a plain httpx GET returns a modern site's empty JS shell (no CSS), so the
old text-only analysis had no real evidence and EVERY profile collapsed to the dataclass
defaults (the same templated design for every site). The router now RENDERS the site via
Firecrawl and hands Claude the screenshot; :func:`extract_site_design` analyzes it with
VISION, so the extracted design genuinely varies per site.

Deep Elementor/Gutenberg block GENERATION (translating this profile into a live
page builder's block tree) is a LATER chunk and is deliberately NOT built here - this
chunk only extracts the profile + attaches it + does a best-effort structural wrap.

Design (mirrors ``policy_ask.run_policy_ask`` / ``content_research.run_content_research``):
the analysis core :func:`extract_site_design` is PURE - the summarizer and the cost
gate are INJECTED - so it unit-tests with a fake summarizer + a fake gate: NO network,
NO DB, NO real provider. It reuses the EXISTING ``content`` money-dial (no new dial):
the single paid Claude call is metered under it and the ACTUAL spend committed after
the call is the Anthropic TOKEN cost only (:func:`pricing.anthropic_cost`).

Degrade, never crash. Every seam that cannot run returns a clean ``status='degraded'``
result (``profile=None``, a machine-branchable ``reason``):

* no Anthropic key / no ``[ai]`` SDK (``summarizer is None``) -> keyless degrade; the
  gate is NOT consulted.
* a cost-gate block (dial off / by-hand, client cap, global spend halt) -> NO provider
  call happens and the gate is NEVER bypassed.
* the analysis call fails (transport / SDK) OR returns no parseable JSON object at all
  -> a clean degrade (the token spend that DID happen is still committed honestly).

A PARTIAL JSON reply (a valid object missing some keys) is NOT a degrade: the tolerant
parser fills every missing field with a sane default, so a thin reply still yields a
usable profile (``status='ok'``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger

if TYPE_CHECKING:
    from integrations.site_analyzer import SiteCapture
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import LLMResult

logger = get_logger("app.services.site_design")

# The EXISTING Content money-dial (schemas/cost.py) - reused, no new dial. The one
# provider this flow spends on; ``job_type`` groups the cost-log rows for the sweep.
_FEATURE = "content"
_PROVIDER_ANTHROPIC = "Anthropic"
_JOB_TYPE = "site_design"

# Stable, machine-branchable degrade reasons surfaced on the response.
DEGRADE_NO_ANTHROPIC = "anthropic_unconfigured"
DEGRADE_ANALYSIS_FAILED = "analysis_failed"

# Bound the rendered content the parser considers salient; hard-cap the total so a
# hostile / huge site cannot balloon the prompt.
_MAX_SECTIONS = 20  # how many section names the profile's section_order may carry (hero->footer)
_MAX_WIREFRAME_CHARS = 20_000  # bound the self-contained wireframe HTML the reply may carry


# --------------------------------------------------------------------------- #
# The summarizer seam (system-prompt-aware).
#
# NOTE: this reuses ``integrations.llm.LLMResult`` but declares its OWN Protocol +
# a real adapter here, because the ``integrations.llm.Summarizer`` seam hard-codes a
# frozen context-module system prompt and takes NO per-call ``system`` override - and
# that module is intentionally not modified by this chunk. This Protocol is the
# minimal system-prompt-aware summarizer the pure core depends on.
# --------------------------------------------------------------------------- #
_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set ANTHROPIC_API_KEY"


@runtime_checkable
class SystemSummarizer(Protocol):
    """Compact ``prompt`` into text under a per-call ``system`` prompt, returning the
    text + token usage. ``model`` selects the tier; ``max_tokens`` bounds the reply.

    ``image_b64`` optionally attaches a base64 PNG (a rendered-page SCREENSHOT) so Claude
    analyzes what the site actually LOOKS LIKE with VISION, not just its text. ``None``
    keeps the plain text-only behaviour."""

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
        image_b64: str | None = None,
    ) -> LLMResult: ...


class AnthropicSystemSummarizer:
    """Real :class:`SystemSummarizer` backed by Claude; lazy-imports the ``anthropic``
    SDK (optional ``[ai]`` extra, exactly like ``integrations.llm.AnthropicSummarizer``).

    Distinct from that summarizer in that it passes a PER-CALL ``system`` prompt (the
    design contract) instead of a frozen preamble AND accepts an optional screenshot for
    VISION analysis. Absent SDK / key -> ``ProviderNotConfiguredError`` naming the fix
    (the builder turns that into a clean keyless degrade). NEVER logs the secret."""

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-5") -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Anthropic summarizer unavailable: {_INSTALL_HINT}")
        try:
            import anthropic
        except ImportError as exc:  # SDK not installed (base install omits the [ai] extra)
            raise ProviderNotConfiguredError(
                f"Anthropic summarizer unavailable: {_INSTALL_HINT}"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
        image_b64: str | None = None,
    ) -> LLMResult:
        # With a screenshot the user turn is a content LIST: the image block FIRST (so
        # Claude looks at the render), then the text block. Without one it stays a plain
        # string (identical to the old text-only behaviour).
        user_content: Any
        if image_b64:
            user_content = [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                },
                {"type": "text", "text": prompt},
            ]
        else:
            user_content = prompt
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        if system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        message = self._client.messages.create(**kwargs)
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = message.usage
        return LLMResult(
            text=text,
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
        )


# --------------------------------------------------------------------------- #
# Provider wiring (key-gated builder; None == degrade) + the gate builder.
# --------------------------------------------------------------------------- #
def build_design_summarizer(settings: Settings) -> SystemSummarizer | None:
    """The key-gated design summarizer, or ``None`` (degraded) when unconfigured.

    Reuses the SAME optional ``anthropic_api_key`` every other AI seam gates on; a
    missing key OR an absent ``[ai]`` SDK returns ``None`` (degrade, never crash). It
    NEVER logs the secret, only the reason."""
    key = settings.anthropic_api_key
    if not key:
        logger.info("site_design_degraded", reason=DEGRADE_NO_ANTHROPIC)
        return None
    try:
        return AnthropicSystemSummarizer(
            api_key=key.get_secret_value(), model=settings.content_design_model
        )
    except ProviderNotConfiguredError:
        logger.info("site_design_degraded", reason="anthropic_sdk_absent")
        return None


class _NullDesignCache:
    """A no-op ``CostCache``: each analysis is a unique live lookup, never a cache hit
    (``cache_key`` is always ``None`` on this flow); the dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def build_design_gate() -> CostGate:
    """The real cost gate over the Postgres cost store (no cache - see ``_NullDesignCache``)."""
    return CostGate(PostgresCostStore(), _NullDesignCache())


# --------------------------------------------------------------------------- #
# The design profile (frozen; every field defaulted so a partial parse is usable).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Palette:
    """The site's core colours (CSS hex strings)."""

    primary: str = "#111827"
    secondary: str = "#4b5563"
    background: str = "#ffffff"
    text: str = "#111827"
    accent: str = "#2563eb"


@dataclass(frozen=True)
class Typography:
    """The site's type system (CSS font-family stacks + a base size)."""

    heading_font: str = "system-ui, sans-serif"
    body_font: str = "system-ui, sans-serif"
    base_size: str = "16px"


@dataclass(frozen=True)
class BlueprintSection:
    """ONE observed section of the analyzed page: its ``kind`` (a section-type name
    from the controlled vocabulary), the ``heading`` text actually shown, and the
    ``layout`` variant it presents in (split / grid / accordion / banner / …). The
    ordered list of these IS the page blueprint - the exact top-to-bottom sequence a
    matching page is built to follow."""

    kind: str = "section"
    heading: str = ""
    layout: str = "stacked"

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "heading": self.heading, "layout": self.layout}


@dataclass(frozen=True)
class Layout:
    """The page skeleton: the full ordered ``blueprint`` (every section's kind +
    heading + layout, in exact top-to-bottom sequence) - the deep structural capture
    a matching page is generated to follow - plus the flat ``section_order`` (the
    kind list, kept for the back-compat publish path), the container width, and the
    hero / CTA presentation styles."""

    container_width: str = "1200px"
    section_order: list[str] = field(
        default_factory=lambda: ["hero", "intro", "services", "proof", "faq", "cta"]
    )
    blueprint: list[BlueprintSection] = field(default_factory=list)
    hero_style: str = "centered"
    cta_style: str = "banner"


@dataclass(frozen=True)
class Components:
    """Reusable component styling cues the new page should echo."""

    button_style: str = "solid rounded"
    card_style: str = "soft shadow"
    spacing_scale: str = "comfortable"


@dataclass(frozen=True)
class SiteDesignProfile:
    """The extracted design system a new page is built to MATCH. Every field has a
    sane default, so a partial (or missing) parse still yields a usable profile.

    ``wireframe_html`` is a SELF-CONTAINED, styled HTML snippet (inline ``<style>`` +
    one ``<section>``) that renders a representative hero/homepage section using the
    EXTRACTED colours + fonts + layout, so a human can SEE what a matching page would
    look like. Empty when the reply carried none (still a usable profile)."""

    palette: Palette = field(default_factory=Palette)
    typography: Typography = field(default_factory=Typography)
    layout: Layout = field(default_factory=Layout)
    components: Components = field(default_factory=Components)
    notes: str = ""
    wireframe_html: str = ""

    def as_dict(self) -> dict[str, Any]:
        """A plain JSON-safe dict whose keys match the ``schemas.content``
        ``SiteDesignProfile`` field names (so the router can round-trip it and the
        publish path can read ``layout.section_order`` back off ``source_pack``)."""
        return {
            "palette": {
                "primary": self.palette.primary,
                "secondary": self.palette.secondary,
                "background": self.palette.background,
                "text": self.palette.text,
                "accent": self.palette.accent,
            },
            "typography": {
                "heading_font": self.typography.heading_font,
                "body_font": self.typography.body_font,
                "base_size": self.typography.base_size,
            },
            "layout": {
                "container_width": self.layout.container_width,
                "section_order": list(self.layout.section_order),
                "blueprint": [s.as_dict() for s in self.layout.blueprint],
                "hero_style": self.layout.hero_style,
                "cta_style": self.layout.cta_style,
            },
            "components": {
                "button_style": self.components.button_style,
                "card_style": self.components.card_style,
                "spacing_scale": self.components.spacing_scale,
            },
            "notes": self.notes,
            "wireframe_html": self.wireframe_html,
        }


@dataclass(frozen=True)
class DesignResult:
    """The verdict of one :func:`extract_site_design` run (a small, comparable value)."""

    status: Literal["ok", "degraded"]
    profile: SiteDesignProfile | None
    reason: str = ""


# --------------------------------------------------------------------------- #
# The strict-JSON design contract (the summarizer's system prompt).
# --------------------------------------------------------------------------- #
_DESIGN_SYSTEM_PROMPT = (
    "You are a senior web + brand designer analyzing a company's EXISTING website so a "
    "new page can be built to MATCH its look and structure. You are given a full-page "
    "SCREENSHOT of the site (what it ACTUALLY looks like when rendered) together with the "
    "page's text content. LOOK AT THE SCREENSHOT FIRST - read the real colours, the real "
    "fonts, the real section rhythm off the pixels - and use the text only to confirm "
    "wording and section order. From ONLY what you observe, extract the site's REAL "
    "visual design system. Respond with STRICT JSON ONLY - no prose, no markdown, no code "
    "fences - an object with EXACTLY these keys: "
    'palette (an object with primary, secondary, background, text, accent - each the '
    'ACTUAL CSS hex colour you SEE, like "#0a0a0a"), typography (an object with '
    "heading_font and body_font - the actual CSS font-family stacks you can identify from "
    'the letterforms/content - and base_size like "16px"), layout (an object with '
    'container_width like "1200px", section_order - an ORDERED array of the section '
    "KIND names ACTUALLY visible top-to-bottom, drawn from header/nav/hero/trust_bar/intro/"
    "services/features/benefits/process/proof/stats/testimonials/reviews/gallery/pricing/about/"
    "team/service_areas/map/faq/cta/contact/footer - capture EVERY section from the top "
    "header/nav down to the bottom footer, in the exact order they appear, omitting none - "
    "blueprint - an ORDERED array (one object PER section, "
    "in exact top-to-bottom sequence) where each object is {kind (the same vocabulary as "
    'section_order), heading (the ACTUAL heading text shown in that section, or ""), layout '
    "(how that section is laid out: split/centered/stacked/grid/numbered-steps/accordion/banner/"
    "carousel/cards/map-embed/tiles/list)} - so the FULL page structure is captured section by "
    "section, not just the kind order - hero_style, and cta_style), components (an "
    "object with button_style, card_style, spacing_scale), notes (a short string of any "
    "other useful observations), and wireframe_html (a SELF-CONTAINED, styled HTML snippet "
    "- an inline <style> block plus ONE <section> - that renders a representative "
    "hero/homepage section using the colours, fonts and layout you extracted, so a human "
    "can SEE how a matching page would look; keep it to one screen, inline every style, "
    "reference no external assets, and make it valid standalone HTML). Report the REAL "
    "design you observe - accurate hexes, real fonts, the true section order - so the "
    "profile VARIES per site; never fall back to a generic template, and never invent a "
    "brand the site does not actually show."
)


# --------------------------------------------------------------------------- #
# Pure helpers: the analysis prompt + the tolerant JSON parse.
# --------------------------------------------------------------------------- #
def build_design_prompt(content: str, *, max_chars: int) -> str:
    """The user turn: the RENDERED page content (Firecrawl markdown, or the joined
    fallback HTML), trimmed to a bounded length. The screenshot rides alongside as a
    vision image block; the system prompt carries the JSON contract - this is the text
    evidence that confirms wording + section order."""
    snippet = (content or "")[: max(1, max_chars)]
    body = snippet if snippet.strip() else "(no page content was rendered - rely on the screenshot)"
    return (
        "Analyze this website (screenshot attached above, if present) and return the "
        "strict-JSON design profile described in the system instructions. The page's "
        "rendered text content follows:\n\n" + body
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from a model reply, tolerating surrounding
    prose / code fences by slicing the outermost ``{...}``. ``None`` on failure
    (mirrors ``content_research._extract_json_object``)."""
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _txt(value: object, default: str) -> str:
    """A stripped non-empty string, else the field's default (never blanks a field)."""
    text = str(value).strip() if value is not None else ""
    return text or default


def _section_list(value: object, *, limit: int) -> list[str]:
    """Coerce a model value into a bounded list of non-empty, deduped section names."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def _blueprint_list(value: object, *, limit: int) -> list[BlueprintSection]:
    """Coerce the model's ``blueprint`` array into a bounded, ordered list of
    :class:`BlueprintSection`. Tolerant: a non-list -> ``[]``; a bare string item ->
    a kind-only section; a dict item -> ``{kind, heading, layout}`` with sane
    fallbacks; a section with no usable kind is skipped. Bounded by ``limit``."""
    if not isinstance(value, list):
        return []
    out: list[BlueprintSection] = []
    for item in value:
        if isinstance(item, str):
            kind = item.strip()
            if kind:
                out.append(BlueprintSection(kind=kind))
        elif isinstance(item, dict):
            kind = str(item.get("kind") or item.get("name") or "").strip()
            if not kind:
                continue
            out.append(
                BlueprintSection(
                    kind=kind,
                    heading=str(item.get("heading") or "").strip(),
                    layout=str(item.get("layout") or "stacked").strip() or "stacked",
                )
            )
        if len(out) >= limit:
            break
    return out


def _wireframe(value: object, *, limit: int) -> str:
    """Coerce the model's ``wireframe_html`` into a bounded HTML string.

    Tolerant: a non-string -> ``""``; a value fenced in ```` ```html ... ``` ```` (the
    model wrapped the snippet in a code fence despite the strict-JSON instruction) is
    unwrapped; the result is hard-capped so a runaway snippet cannot balloon the row."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.startswith("```"):
        # Drop the opening fence line (``` or ```html) and any trailing fence.
        newline = text.find("\n")
        text = text[newline + 1 :] if newline != -1 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    return text[:limit]


def build_profile(data: dict[str, Any]) -> SiteDesignProfile:
    """Build a :class:`SiteDesignProfile` from a parsed JSON object, filling every
    missing / malformed field with the dataclass default (so a thin reply is usable)."""
    defaults = SiteDesignProfile()
    p = _as_dict(data.get("palette"))
    palette = Palette(
        primary=_txt(p.get("primary"), defaults.palette.primary),
        secondary=_txt(p.get("secondary"), defaults.palette.secondary),
        background=_txt(p.get("background"), defaults.palette.background),
        text=_txt(p.get("text"), defaults.palette.text),
        accent=_txt(p.get("accent"), defaults.palette.accent),
    )
    t = _as_dict(data.get("typography"))
    typography = Typography(
        heading_font=_txt(t.get("heading_font"), defaults.typography.heading_font),
        body_font=_txt(t.get("body_font"), defaults.typography.body_font),
        base_size=_txt(t.get("base_size"), defaults.typography.base_size),
    )
    ly = _as_dict(data.get("layout"))
    blueprint = _blueprint_list(ly.get("blueprint"), limit=_MAX_SECTIONS)
    # section_order: the explicit array if given, else DERIVED from the blueprint kinds
    # (so the two views stay consistent), else the dataclass default.
    section_order = (
        _section_list(ly.get("section_order"), limit=_MAX_SECTIONS)
        or [s.kind for s in blueprint]
        or list(defaults.layout.section_order)
    )
    layout = Layout(
        container_width=_txt(ly.get("container_width"), defaults.layout.container_width),
        section_order=section_order,
        blueprint=blueprint,
        hero_style=_txt(ly.get("hero_style"), defaults.layout.hero_style),
        cta_style=_txt(ly.get("cta_style"), defaults.layout.cta_style),
    )
    c = _as_dict(data.get("components"))
    components = Components(
        button_style=_txt(c.get("button_style"), defaults.components.button_style),
        card_style=_txt(c.get("card_style"), defaults.components.card_style),
        spacing_scale=_txt(c.get("spacing_scale"), defaults.components.spacing_scale),
    )
    return SiteDesignProfile(
        palette=palette,
        typography=typography,
        layout=layout,
        components=components,
        notes=_txt(data.get("notes"), defaults.notes),
        wireframe_html=_wireframe(data.get("wireframe_html"), limit=_MAX_WIREFRAME_CHARS),
    )


# --------------------------------------------------------------------------- #
# The MEASURED path: a real Playwright capture (integrations.site_analyzer), reusing
# app.modules.site_builder.service's DOM analysis rather than re-implementing it. This
# is the PREFERRED evidence source (real getComputedStyle values, not an LLM guessing
# hex codes off one screenshot) - see analyze_website_design below, which prefers this
# and falls back to extract_site_design (the vision-LLM path above) only when a real
# browser capture degrades (Playwright not installed, or the target site could not be
# captured at all).
# --------------------------------------------------------------------------- #
def profile_from_capture(capture: SiteCapture) -> SiteDesignProfile:
    """Build a :class:`SiteDesignProfile` from a REAL, Playwright-measured
    ``SiteCapture`` (``integrations.site_analyzer``).

    Reuses ``app.modules.site_builder.service.design_ir_from_capture`` (the SAME DOM
    analysis Site Builder already relies on: mode-color palette extraction, computed
    typography, heading-keyword section classification) rather than re-deriving it,
    then reshapes that DesignIR-shaped dict into content's own profile dataclass via
    the EXISTING tolerant :func:`build_profile` parser - so a thin/partial capture is
    just as usable here as a thin/partial LLM reply already is."""
    from app.modules.site_builder.service import design_ir_from_capture

    ir = design_ir_from_capture(capture, source_type="existing_site", source_url=capture.url)
    layout_px = (ir.get("layout") or {}).get("container_width_px")
    return build_profile(
        {
            "palette": ir.get("palette") or {},
            "typography": ir.get("typography") or {},
            "layout": {
                "container_width": f"{int(layout_px)}px" if layout_px else None,
                "section_order": (ir.get("layout") or {}).get("section_order") or [],
                "blueprint": [
                    {"kind": s.get("kind"), "heading": s.get("heading"), "layout": s.get("layout")}
                    for s in (ir.get("sections") or [])
                ],
            },
            "components": ir.get("components") or {},
            "notes": ir.get("notes") or "",
        }
    )


def analyze_website_design(url: str) -> DesignResult:
    """The preferred, MEASURED analysis: a real Playwright capture of ``url`` (desktop
    viewport only - a single-page design match needs no responsive breakpoint data),
    turned into a :class:`SiteDesignProfile`. Degrades (never crashes, never blocks)
    when Playwright is not installed OR the target site could not be captured (bot
    protection, timeout, ...) - the caller falls back to :func:`extract_site_design`
    (the vision-LLM path) in that case. NOTE: this call is BLOCKING (a real browser
    navigation) - the caller MUST run it off the event loop (``asyncio.to_thread``),
    exactly like the vision-LLM path already does for its own blocking calls."""
    from integrations.site_analyzer import DEFAULT_VIEWPORTS, analyze_website, build_site_analyzer

    result = analyze_website(url, analyzer=build_site_analyzer(), viewports=DEFAULT_VIEWPORTS[:1])
    if result.status != "ok" or result.capture is None:
        return _degraded(f"playwright:{result.reason}")
    return DesignResult(status="ok", profile=profile_from_capture(result.capture), reason="")


# --------------------------------------------------------------------------- #
# The pure, injectable core.
# --------------------------------------------------------------------------- #
def _degraded(reason: str) -> DesignResult:
    return DesignResult(status="degraded", profile=None, reason=reason)


def extract_site_design(
    *,
    summarizer: SystemSummarizer | None,
    gate: CostGate,
    settings: Settings,
    content: str,
    screenshot_b64: str | None,
) -> DesignResult:
    """Analyze the RENDERED site (a screenshot + its text) and extract the site's
    :class:`SiteDesignProfile`.

    Pure of network/DB (the summarizer + gate are injected; the fetch/render already
    happened in the router). ``content`` is the rendered markdown (or joined fallback
    HTML); ``screenshot_b64`` is the base64 PNG Claude analyzes with VISION (``None`` ->
    text-only). The gate contract is reused verbatim (evaluate -> call -> commit): on any
    non-allowed outcome NO provider call happens and the gate is not bypassed. The single
    paid call is metered under the ``content`` dial, and the ACTUAL cost committed after
    the call is the Anthropic TOKEN cost only (:func:`pricing.anthropic_cost`). Degrades,
    never crashes.
    """
    # Claude is the WHOLE analysis engine; without a key there is nothing to run, so a
    # missing summarizer is a keyless degrade BEFORE the gate is ever consulted.
    if summarizer is None:
        return _degraded(DEGRADE_NO_ANTHROPIC)

    prompt = build_design_prompt(
        content,
        max_chars=settings.content_design_max_html_chars * max(1, settings.content_design_max_pages),
    )
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,  # org-level staff analysis; still under the global spend halt
        provider=_PROVIDER_ANTHROPIC,
        estimated_cost=float(settings.content_generate_cost_estimate),
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # dial off / by-hand, client cap, or the global spend halt: NO provider call.
        return _degraded(f"cost_gate:{decision.outcome}")

    model = settings.content_design_model
    try:
        result = summarizer.summarize(
            prompt,
            model=model,
            max_tokens=settings.content_design_max_tokens,
            system=_DESIGN_SYSTEM_PROMPT,
            image_b64=screenshot_b64,
        )
    except Exception:  # transport / SDK failure: degrade, don't crash (usage unknown -> nothing billed)
        logger.info("site_design_analysis_failed")
        return _degraded(DEGRADE_ANALYSIS_FAILED)

    # The call ran (tokens were consumed): commit the ACTUAL TOKEN cost honestly even
    # if the reply turns out to be unparseable below.
    gate.commit(
        ctx,
        pricing.anthropic_cost(
            settings,
            model=model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
    )

    data = _extract_json_object(result.text)
    if data is None:
        # A reply with no JSON object at all is not usable -> degrade (spend committed).
        return _degraded(DEGRADE_ANALYSIS_FAILED)
    return DesignResult(status="ok", profile=build_profile(data), reason="")
