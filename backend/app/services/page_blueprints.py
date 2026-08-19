"""The SHARED page-layout doctrine: 7 named page TEMPLATES (audited section
sequences) + the blueprint resolver both the dashboard content generator AND the
Claude Code skills build against.

WHY THIS MODULE EXISTS. A generated page should MIRROR the section sequence + the
component styling that top-ranking pages of its type actually use - not the current
"wrap by <h2>, name generically, carry palette only". Two things drive that:

* an ANALYZED blueprint - the exact ordered sections of the CLIENT's own site (or a
  top competitor), extracted by ``site_design.extract_site_design`` via vision; and
* a pre-made TEMPLATE - the canonical, audited best-practice sequence for a page
  type (service / location / service-area / blog / faq / local / homepage).

Both reduce to ONE representation here - an ordered list of :class:`SectionSpec`
(a section ``kind`` + a suggested ``heading`` + a ``layout`` variant) - so the
publish path (``workers.tasks.content._shape_body_html`` + ``services.elementor``)
follows the SAME sequence + applies the SAME per-kind component styling whether the
structure came from the analyzed site or a chosen template.

THE AUDIT (encoded as the default rules below). The template sequences are grounded
in a survey of what top-ranking / high-converting pages actually do (Backlinko,
Ahrefs, NN/g, BrightLocal, Whitespark, Synup, Search Engine Land, Sterling Sky,
involve.me, Prismic). The recurring invariants the survey found are encoded as rules:
``hero`` is always first; a trust / social-proof block sits high (right under the
hero) on every commercial (non-blog) type; and a ``cta`` is always the last content
section. See ``docs`` / the generated ``PAGE-TEMPLATES.md`` skills reference.

SHARED WITH THE SKILLS. This module is the ONE source of truth. :func:`render_markdown`
renders the templates as the human-readable reference the Claude Code skills read at
``.claude/skills/_shared/reference/PAGE-TEMPLATES.md``; a drift-lock unit test asserts
the committed doc equals this module's rendering, so the two can never diverge.

Pure + dependency-free (stdlib only): no network, no DB, no provider, no clock - so it
unit-tests trivially and both the worker and a skill can import/read it cheaply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# The controlled vocabulary (a closed set keeps templates + the extractor + the
# styler in lock-step; an unknown kind still renders, but only these are canonical).
# --------------------------------------------------------------------------- #
# Section KINDS a page can be built from (snake_case; the ``aios-<kind>`` CSS class).
SECTION_KINDS: frozenset[str] = frozenset(
    {
        "hero", "trust_bar", "intro", "usp", "pain_points", "solution",
        "services", "features", "benefits", "process", "proof", "stats",
        "testimonials", "reviews", "gallery", "case_studies", "pricing",
        "about", "team", "service_areas", "map", "faq", "search", "related",
        "conclusion", "cta", "contact", "hours", "lead_form", "body",
    }
)
# LAYOUT variants a section can present in (the ``aios-layout-<variant>`` CSS class
# + the per-variant component styling the publish path applies).
LAYOUT_VARIANTS: frozenset[str] = frozenset(
    {
        "stacked", "centered", "split", "grid", "numbered-steps", "accordion",
        "banner", "carousel", "cards", "map-embed", "toc", "list", "nap", "tiles",
    }
)

_DEFAULT_LAYOUT = "stacked"


# --------------------------------------------------------------------------- #
# The two shapes: one section, and a whole page blueprint.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SectionSpec:
    """ONE section of a page: its ``kind`` (from :data:`SECTION_KINDS`), a suggested
    ``heading`` (a display label; the generator's own H2 wins when it has copy), the
    ``layout`` variant it presents in, and two routing flags.

    ``content`` marks a section that CARRIES generated body copy (intro, benefits,
    faq, cta, ...) - the publish path assigns the draft's ``<h2>`` groups to these,
    in order. A ``content=False`` section is CHROME (trust_bar, map, gallery, search,
    ...) the theme / AIOS Publisher plugin supplies from live data; the wrapper never
    fabricates copy for it. ``absorb`` marks the ONE section that soaks up overflow
    when the draft has more groups than the blueprint has content sections (the blog
    ``body`` container); at most one per blueprint, else the last content section.
    """

    kind: str
    heading: str = ""
    layout: str = _DEFAULT_LAYOUT
    content: bool = True
    absorb: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "heading": self.heading,
            "layout": self.layout,
            "content": self.content,
            "absorb": self.absorb,
        }


@dataclass(frozen=True)
class PageBlueprint:
    """A named page TEMPLATE: an ordered sequence of :class:`SectionSpec` + the job
    ``page_type`` it best maps to. ``section_order`` is the flat list of kinds (the
    back-compat view the old publish path consumed)."""

    template: str
    label: str
    page_type: str
    sections: tuple[SectionSpec, ...]
    notes: str = ""

    @property
    def section_order(self) -> list[str]:
        """The flat ordered kind list (back-compat with ``layout.section_order``)."""
        return [s.kind for s in self.sections]

    def as_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "label": self.label,
            "page_type": self.page_type,
            "sections": [s.as_dict() for s in self.sections],
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# The 7 pre-made templates (the audited default section sequences).
# --------------------------------------------------------------------------- #
def _s(
    kind: str, heading: str, layout: str = _DEFAULT_LAYOUT, *, content: bool = True, absorb: bool = False
) -> SectionSpec:
    return SectionSpec(kind=kind, heading=heading, layout=layout, content=content, absorb=absorb)


TEMPLATES: dict[str, PageBlueprint] = {
    # 1. SERVICE - a single service. Split hero, trust high, benefits/features grids,
    # numbered process, proof + testimonials, pricing, FAQ accordion, closing CTA.
    "service": PageBlueprint(
        "service", "Service page", "service",
        (
            _s("hero", "{primary}", "split"),
            _s("trust_bar", "Trusted by", "carousel", content=False),
            _s("intro", "Why {primary} matters"),
            _s("benefits", "The benefits of choosing {client}", "grid"),
            _s("features", "What's included", "grid"),
            _s("process", "How it works", "numbered-steps"),
            _s("proof", "Proven results"),
            _s("testimonials", "What clients say", "carousel"),
            _s("pricing", "Pricing", "cards"),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("cta", "Get started with {primary}", "banner"),
        ),
        notes="Split hero + a repeated CTA (hero + bottom banner); benefits/features as grids.",
    ),
    # 2. LOCATION - one physical location. NAP high, location-specific services +
    # reviews, team, gallery of the real place, embedded map, sibling areas, FAQ, CTA.
    "location": PageBlueprint(
        "location", "Location page", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("contact", "Visit us", "nap", content=False),
            _s("hours", "Opening hours", "list", content=False),
            _s("intro", "About our {city} location"),
            _s("services", "Services at this location", "grid"),
            _s("reviews", "Local reviews", "carousel", content=False),
            _s("team", "Meet the team", "cards", content=False),
            _s("gallery", "Our {city} location", "grid", content=False),
            _s("map", "Find us", "map-embed", content=False),
            _s("service_areas", "Areas we serve nearby", "list", content=False),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("cta", "Book at our {city} location", "banner"),
        ),
        notes="Location-specific hero + real photos; NAP/hours/map are theme-supplied chrome.",
    ),
    # 3. SERVICE-AREA - a service across an area (often NO address there): lead with
    # service + area proof, an explicit covered-areas list, benefits, local reviews.
    "service_area": PageBlueprint(
        "service_area", "Service-area page", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("trust_bar", "Trusted locally", "carousel", content=False),
            _s("intro", "Serving {city} and the surrounding area"),
            _s("services", "What we offer in {city}", "grid"),
            _s("service_areas", "Areas we cover", "list"),
            _s("benefits", "Why choose {client}", "grid"),
            _s("reviews", "What local customers say", "carousel", content=False),
            _s("process", "How it works", "numbered-steps"),
            _s("map", "Our coverage area", "map-embed", content=False),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("cta", "Request {primary} in {city}", "banner"),
        ),
        notes="Lead with service + unique local content, not NAP; explicit covered-areas list.",
    ),
    # 4. BLOG - the structural outlier: the middle is a REPEATABLE body container that
    # absorbs the draft's H2 blocks; sticky ToC on top, proof, FAQ, conclusion, CTA.
    "blog": PageBlueprint(
        "blog", "Blog / article", "blog",
        (
            _s("hero", "{primary}", "stacked"),
            _s("intro", "Introduction"),
            _s("related", "In this article", "toc", content=False),
            _s("body", "", "stacked", absorb=True),
            _s("proof", "The evidence"),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("conclusion", "Conclusion"),
            _s("cta", "Next steps", "banner"),
        ),
        notes="Stacked hero (title + featured image); body absorbs the H2 blocks; sticky ToC.",
    ),
    # 5. FAQ - a Q&A hub: brief intro, a search box + category nav (chrome), the Q&A
    # accordion body (absorbs the question blocks), links out, a contact fallback CTA.
    "faq": PageBlueprint(
        "faq", "FAQ page", "blog",
        (
            _s("hero", "Frequently asked questions", "centered"),
            _s("search", "Search the FAQ", "stacked", content=False),
            _s("related", "Browse by topic", "list", content=False),
            _s("faq", "Questions & answers", "accordion", absorb=True),
            _s("cta", "Still have questions?", "banner"),
        ),
        notes="Accordion for 10+ questions (plain list under ~10); simplest questions first.",
    ),
    # 6. LOCAL - a local business landing / local homepage: hero with tap-to-call +
    # rating, services, about, reviews, covered areas, map, one bottom CTA.
    "local": PageBlueprint(
        "local", "Local business landing", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("trust_bar", "Rated by locals", "carousel", content=False),
            _s("services", "Our services", "grid"),
            _s("about", "About {client}"),
            _s("reviews", "Customer reviews", "carousel", content=False),
            _s("service_areas", "Areas we serve", "list"),
            _s("map", "Where we are", "map-embed", content=False),
            _s("cta", "Call {client} today", "banner"),
        ),
        notes="H1 = service + location + differentiator; primary CTA is tap-to-call.",
    ),
    # 7. HOMEPAGE - a company homepage: hero + logo trust strip, benefits/features
    # grids, proof + testimonials, about, big-number stat tiles, a repeated CTA.
    "homepage": PageBlueprint(
        "homepage", "Homepage", "service",
        (
            _s("hero", "{client}", "split"),
            _s("trust_bar", "Trusted by", "carousel", content=False),
            _s("benefits", "What you get", "grid"),
            _s("features", "How it works", "grid"),
            _s("proof", "Proven results"),
            _s("testimonials", "What clients say", "carousel"),
            _s("about", "About {client}"),
            _s("stats", "By the numbers", "tiles", content=False),
            _s("cta", "Get started", "banner"),
        ),
        notes="One primary CTA repeated top + bottom; logo trust strip under the hero.",
    ),
}

# The job ``page_type`` -> the template it defaults to when the operator picks none.
# ``gbp_post`` is a single compact GBP card, not a full page, so it maps to nothing
# (the publish path keeps its existing behaviour).
_PAGE_TYPE_TEMPLATE: dict[str, str] = {
    "service": "service",
    "local": "local",
    "blog": "blog",
}


# --------------------------------------------------------------------------- #
# Public accessors.
# --------------------------------------------------------------------------- #
def template_names() -> list[str]:
    """The 7 canonical template keys, in a stable order."""
    return list(TEMPLATES.keys())


def get_template(name: str | None) -> PageBlueprint | None:
    """The blueprint for a template key, or ``None`` for an unknown / empty key."""
    if not name:
        return None
    return TEMPLATES.get(name)


def template_for_page_type(page_type: str) -> PageBlueprint | None:
    """The DEFAULT template for a job page type (service->service, local->local,
    blog->blog); ``None`` for a type with no full-page template (e.g. gbp_post)."""
    return TEMPLATES.get(_PAGE_TYPE_TEMPLATE.get(page_type, ""))


# --------------------------------------------------------------------------- #
# Coercion: a raw blueprint (from an analyzed profile) -> SectionSpec list.
# --------------------------------------------------------------------------- #
def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_layout(value: Any, *, kind: str) -> str:
    """A known layout variant, else a sensible default for the kind."""
    text = str(value or "").strip()
    if text in LAYOUT_VARIANTS:
        return text
    return _default_layout_for(kind)


def _default_layout_for(kind: str) -> str:
    """The natural layout variant for a section kind (used when none is supplied)."""
    return _KIND_DEFAULT_LAYOUT.get(kind, _DEFAULT_LAYOUT)


_KIND_DEFAULT_LAYOUT: dict[str, str] = {
    "hero": "split",
    "trust_bar": "carousel",
    "services": "grid",
    "features": "grid",
    "benefits": "grid",
    "process": "numbered-steps",
    "testimonials": "carousel",
    "reviews": "carousel",
    "gallery": "grid",
    "pricing": "cards",
    "team": "cards",
    "stats": "tiles",
    "faq": "accordion",
    "map": "map-embed",
    "cta": "banner",
    "service_areas": "list",
    "related": "list",
    "contact": "nap",
}
# Section kinds that are CHROME by default (theme / plugin supplied, no generated copy)
# when a raw section omits an explicit ``content`` flag.
_CHROME_KINDS: frozenset[str] = frozenset(
    {"trust_bar", "map", "gallery", "search", "hours", "contact", "lead_form", "stats", "reviews"}
)


def section_from_raw(raw: Any) -> SectionSpec | None:
    """Coerce ONE raw section (a dict ``{kind, heading?, layout?, ...}`` or a bare
    kind string) into a :class:`SectionSpec`; ``None`` when it has no usable kind."""
    if isinstance(raw, str):
        kind = raw.strip()
        if not kind:
            return None
        return SectionSpec(
            kind=kind,
            layout=_default_layout_for(kind),
            content=kind not in _CHROME_KINDS,
        )
    d = _as_dict(raw)
    kind = str(d.get("kind") or d.get("name") or "").strip()
    if not kind:
        return None
    content = d.get("content")
    return SectionSpec(
        kind=kind,
        heading=str(d.get("heading") or "").strip(),
        layout=_coerce_layout(d.get("layout"), kind=kind),
        content=bool(content) if content is not None else kind not in _CHROME_KINDS,
        absorb=bool(d.get("absorb", False)),
    )


def sections_from_raw(raw: Any) -> list[SectionSpec]:
    """Coerce a raw blueprint (a list of section dicts OR bare kind strings) into an
    ordered, de-duplicated-by-nothing list of :class:`SectionSpec` (empty on junk)."""
    if not isinstance(raw, list):
        return []
    out: list[SectionSpec] = []
    for item in raw:
        spec = section_from_raw(item)
        if spec is not None:
            out.append(spec)
    return out


# --------------------------------------------------------------------------- #
# The resolver: pick the effective blueprint for a job (precedence-ordered).
# --------------------------------------------------------------------------- #
def resolve_blueprint(
    *,
    design_profile: dict[str, Any] | None,
    template: str | None,
    page_type: str,
) -> list[SectionSpec]:
    """The ONE effective ordered blueprint a job's page is built to, by precedence:

    1. an EXPLICITLY chosen TEMPLATE (one of the 7) - if the operator picked a template,
       the page is built to it and the content is slotted into ITS sections;
    2. else the ANALYZED profile's rich ``layout.blueprint`` (the client's real sections)
       - so a page with no template mirrors the client's own analyzed site EXACTLY;
    3. else the analyzed profile's ``layout.section_order`` (names only -> default layouts);
    4. else the DEFAULT template for the page type (service/local/blog);
    5. else ``[]`` - nothing to shape by (the publish path keeps its plain behaviour).

    So "pick a template -> use the template; otherwise mirror the analyzed site". Returns
    a list of :class:`SectionSpec` (possibly empty). Degrade-safe: a malformed / unknown
    input at any tier falls through to the next.
    """
    chosen = get_template(template)
    if chosen is not None:
        return list(chosen.sections)
    profile = _as_dict(design_profile)
    layout = _as_dict(profile.get("layout"))
    analyzed = sections_from_raw(layout.get("blueprint"))
    if analyzed:
        return analyzed
    from_order = sections_from_raw(layout.get("section_order"))
    if from_order:
        return from_order
    default = template_for_page_type(page_type)
    if default is not None:
        return list(default.sections)
    return []


# --------------------------------------------------------------------------- #
# The skills reference doc (rendered from THIS module -> the single source of truth).
# --------------------------------------------------------------------------- #
def render_markdown() -> str:
    """Render the 7 templates as the Markdown reference the Claude Code skills read
    (``.claude/skills/_shared/reference/PAGE-TEMPLATES.md``). A drift-lock test asserts
    the committed file equals this output, so the doc can never drift from the code."""
    lines: list[str] = [
        "# Page-layout templates (the shared layout doctrine)",
        "",
        "> GENERATED from `backend/app/services/page_blueprints.py` — do not edit by",
        "> hand. Run `python -m app.services.page_blueprints` to regenerate; a unit test",
        "> (`tests/test_page_blueprints.py`) fails if this file drifts from the module.",
        "",
        "These are the canonical, audited section sequences a generated page of each",
        "type is built to. The dashboard content generator and these skills resolve the",
        "SAME blueprint, so a page's structure matches whether it was shaped by an",
        "analyzed site or a chosen template. Invariants: `hero` is first; a trust /",
        "social-proof block sits high on commercial types; `cta` is the last content",
        "section. A `content=false` section is CHROME (trust bars, maps, galleries,",
        "search) the theme / AIOS Publisher plugin supplies — never fabricated copy.",
        "",
        "Section kinds are drawn from a controlled vocabulary; each carries a layout",
        "variant (`split`/`grid`/`numbered-steps`/`accordion`/`banner`/…) the publish",
        "path renders as a styled component.",
        "",
    ]
    for name in template_names():
        bp = TEMPLATES[name]
        lines.append(f"## {bp.label}  (`template={bp.template}`)")
        lines.append("")
        lines.append(f"Default for page type: `{bp.page_type}`. {bp.notes}")
        lines.append("")
        lines.append("| # | kind | layout | role | heading |")
        lines.append("|---|------|--------|------|---------|")
        for i, s in enumerate(bp.sections, start=1):
            role = "content" if s.content else "chrome"
            if s.absorb:
                role += " (absorbs overflow)"
            heading = s.heading or "-"
            lines.append(f"| {i} | `{s.kind}` | `{s.layout}` | {role} | {heading} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":  # pragma: no cover - regeneration convenience
    print(render_markdown(), end="")
