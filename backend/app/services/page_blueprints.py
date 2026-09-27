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
        # SITE CHROME. Canonical because the design extractor legitimately REPORTS it:
        # a vision pass over a rendered page sees the header, the nav and the footer, and
        # 4 of 6 page kinds in a live sweep (2026-09-25) emitted them. Leaving them out
        # of the vocabulary did not stop them arriving - it only meant they arrived as
        # "unknown", which `section_from_raw` then treated as CONTENT-BEARING, so the
        # writer was asked to produce body copy for a "header" section and `hero` was no
        # longer the page's first content block (the doctrine invariant above).
        "header", "nav", "footer", "breadcrumbs", "sidebar",
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
    #: THE CLIENT DATA THIS SECTION CANNOT BE WRITTEN WITHOUT, or "" when the writer can
    #: produce it from the brief alone. A slot naming an evidence source the client did
    #: not supply is DROPPED from the page - never filled with invented prices, invented
    #: quotes or a generic "transparent pricing tailored to your needs".
    #:
    #: This is what makes a FIXED 7-section wireframe safe. Without it the writer meets a
    #: `pricing` slot with no prices and does what a writer does: makes something up.
    #: Known sources: testimonials | pricing | reviews | nap | areas | team | stats |
    #: links | proof.
    evidence: str = ""
    #: CAPACITY, carried from the measured design (``site_design.BlueprintSection``).
    #: ``max_items`` is how many repeated items the section actually presents - three
    #: pricing cards, four testimonials. 0 means unmeasured, and a generator must then
    #: fall back to its own judgement rather than to zero.
    #:
    #: Before these existed the blueprint could say "this page has a pricing section"
    #: and not "it holds three cards", so a draft with seven plans was slotted in and
    #: the overflow absorbed - a design-aware pipeline that was only aware of order.
    max_items: int = 0
    heading_chars: int = 0
    body_chars: int = 0

    @property
    def has_capacity(self) -> bool:
        """Whether anything about this section's capacity was actually measured."""
        return bool(self.max_items or self.heading_chars or self.body_chars)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "heading": self.heading,
            "layout": self.layout,
            "content": self.content,
            "absorb": self.absorb,
            "evidence": self.evidence,
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
    kind: str,
    heading: str,
    layout: str = _DEFAULT_LAYOUT,
    *,
    content: bool = True,
    absorb: bool = False,
    evidence: str = "",
) -> SectionSpec:
    return SectionSpec(
        kind=kind, heading=heading, layout=layout, content=content, absorb=absorb,
        evidence=evidence,
    )


TEMPLATES: dict[str, PageBlueprint] = {
    # EVERY TEMPLATE IS EXACTLY SEVEN SECTIONS (operator's decision, 2026-09-26).
    #
    # WHAT THIS REPLACED, and why the replacement is the point. These sequences used to be
    # 8-12 sections of audited best practice, applied as a WRAPPER over whatever the writer
    # had already produced as free-form markdown. So a service page had eleven named slots
    # and a draft with its own invented headings; the wrapper found nothing to put in
    # "Pricing" or "What clients say", and the published page collapsed to a hero, a wall of
    # prose and a CTA. Measured on a real client push: 11 slots specified, 3 rendered.
    #
    # Seven is a number a writer can be held to and an operator can check at a glance. The
    # sequence below is now a SPECIFICATION THE WRITER FILLS - one typed payload per slot -
    # not a shape imposed afterwards on prose that ignored it.
    #
    # EVERY TEMPLATE HAS THE SAME SHAPE, deliberately:
    #   * `hero` first and `cta` last (the doctrine invariant).
    #   * FIVE slots the writer can always fill from the brief.
    #   * TWO slots gated on CLIENT EVIDENCE. Supplied -> a seven-section page. Not
    #     supplied -> those two drop, and the page is five real sections instead of seven
    #     with two fabrications in it.
    #
    # 1. SERVICE - one service, sold: what is included, how it runs, what it answers.
    "service": PageBlueprint(
        "service", "Service page", "service",
        (
            _s("hero", "{primary}", "split"),
            _s("features", "What's included", "grid"),
            _s("process", "How it works", "numbered-steps"),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("testimonials", "What clients say", "carousel", evidence="testimonials"),
            _s("pricing", "Pricing", "cards", evidence="pricing"),
            _s("cta", "Get started with {primary}", "banner"),
        ),
        notes="Split hero; deliverables as a grid; numbered process; proof + price last.",
    ),
    # 2. LOCATION - one physical place. The address block and the reviews are what make it
    # a LOCATION page rather than a service page with a city in it, and both are client
    # data - so both are gated.
    "location": PageBlueprint(
        "location", "Location page", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("intro", "About our {city} location"),
            _s("services", "Services at this location", "grid"),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("contact", "Visit us", "nap", content=False, evidence="nap"),
            _s("reviews", "Local reviews", "carousel", content=False, evidence="reviews"),
            _s("cta", "Book at our {city} location", "banner"),
        ),
        notes="Hero + local intro + services; NAP and reviews render only from real data.",
    ),
    # 3. SERVICE-AREA - a service across an area, usually with no address in it. The
    # covered-areas list is the page's reason to exist, so it is gated on real areas.
    "service_area": PageBlueprint(
        "service_area", "Service-area page", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("intro", "Serving {city} and the surrounding area"),
            _s("services", "What we offer in {city}", "grid"),
            _s("process", "How it works", "numbered-steps"),
            _s("service_areas", "Areas we cover", "list", evidence="areas"),
            _s("reviews", "What local customers say", "carousel", content=False, evidence="reviews"),
            _s("cta", "Request {primary} in {city}", "banner"),
        ),
        notes="Service + area content first; the covered-areas list is the page's spine.",
    ),
    # 4. BLOG / ARTICLE - the structural outlier: the middle is ONE repeatable body
    # container that absorbs the article's H2 blocks. The other six stay typed.
    "blog": PageBlueprint(
        "blog", "Blog / article", "blog",
        (
            _s("hero", "{primary}", "stacked"),
            _s("intro", "Introduction"),
            _s("body", "", "stacked", absorb=True),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("conclusion", "Conclusion"),
            _s("proof", "The evidence", evidence="proof"),
            _s("cta", "Next steps", "banner"),
        ),
        notes="Stacked hero; body absorbs the H2 blocks; evidence block only when cited.",
    ),
    # 5. FAQ - a question hub. The accordion absorbs the Q&A; the rest frames it.
    "faq": PageBlueprint(
        "faq", "FAQ page", "blog",
        (
            _s("hero", "Frequently asked questions", "centered"),
            _s("intro", "What this page answers"),
            _s("faq", "Questions & answers", "accordion", absorb=True),
            _s("services", "What we do", "grid"),
            _s("proof", "Where these answers come from", evidence="proof"),
            _s("related", "Related reading", "list", content=False, evidence="links"),
            _s("cta", "Still have questions?", "banner"),
        ),
        notes="Accordion body; a services grid so the page sells as well as answers.",
    ),
    # 6. LOCAL - a local business landing page, often the site's front door.
    "local": PageBlueprint(
        "local", "Local business landing", "local",
        (
            _s("hero", "{primary} in {city}", "split"),
            _s("services", "Our services", "grid"),
            _s("about", "About {client}"),
            _s("faq", "Frequently asked questions", "accordion"),
            _s("service_areas", "Areas we serve", "list", evidence="areas"),
            _s("reviews", "Customer reviews", "carousel", content=False, evidence="reviews"),
            _s("cta", "Call {client} today", "banner"),
        ),
        notes="H1 = service + location + differentiator; the CTA is tap-to-call.",
    ),
    # 7. HOMEPAGE - the company front door: what you do, for whom, proved.
    "homepage": PageBlueprint(
        "homepage", "Homepage", "service",
        (
            _s("hero", "{client}", "split"),
            _s("benefits", "What you get", "grid"),
            _s("services", "What we do", "grid"),
            _s("process", "How it works", "numbered-steps"),
            _s("about", "About {client}"),
            _s("testimonials", "What clients say", "carousel", evidence="testimonials"),
            _s("cta", "Get started", "banner"),
        ),
        notes="One primary CTA repeated top + bottom; proof only where proof exists.",
    ),
    # 8. ABOUT - the page a buyer opens before they decide to trust you. Added
    # 2026-09-26: the operator asked for it by name, and it was the one common page type
    # with no template at all, so an about page was being built to the SERVICE wireframe.
    "about": PageBlueprint(
        "about", "About page", "service",
        (
            _s("hero", "About {client}", "split"),
            _s("intro", "Why we exist"),
            _s("benefits", "What we stand for", "grid"),
            _s("process", "How we work", "numbered-steps"),
            _s("team", "The people behind {client}", "cards", evidence="team"),
            _s("stats", "By the numbers", "tiles", evidence="stats"),
            _s("cta", "Work with {client}", "banner"),
        ),
        notes="Story first, values as a grid, people and numbers only when they are real.",
    ),
}

# The job ``page_type`` -> the template it defaults to when the operator picks none.
# ``gbp_post`` is a single compact GBP card, not a full page, so it maps to nothing
# (the publish path keeps its existing behaviour).
#: Which template a page type DEFAULTS to when the operator chose none.
#:
#: The four keys a job row can actually carry are the `content_page_type` enum's:
#: service, blog, local, gbp_post. `about` is here because a page type and a template are
#: different axes - `about` is a TEMPLATE an operator selects for a company page, and it
#: is selected on a `service`-typed job. The entry costs nothing and means the mapping is
#: already right if `about` is ever added to the enum; `gbp_post` is absent on purpose,
#: because a Google Business post is not a page and has no full-page wireframe.
_PAGE_TYPE_TEMPLATE: dict[str, str] = {
    "service": "service",
    "local": "local",
    "blog": "blog",
    "about": "about",
}


# --------------------------------------------------------------------------- #
# Public accessors.
# --------------------------------------------------------------------------- #
def template_names() -> list[str]:
    """The canonical template keys, in a stable order."""
    return list(TEMPLATES.keys())


def get_template(name: str | None) -> PageBlueprint | None:
    """The blueprint for a template key, or ``None`` for an unknown / empty key."""
    if not name:
        return None
    return TEMPLATES.get(name)


def _normalize_page_type(page_type: str) -> str:
    """A page type reduced to its comparison key: lowercased, trimmed, hyphens as
    underscores. So ``"Service-Area"``, ``"service_area"`` and ``" SERVICE AREA "``
    are one key - which matters because these values arrive from a job row, a brand
    kit's JSON and an operator's wizard, and those three have never agreed on case."""
    return str(page_type or "").strip().lower().replace("-", "_").replace(" ", "_")


def template_for_page_type(page_type: str) -> PageBlueprint | None:
    """The DEFAULT template for a job page type (service->service, local->local,
    blog->blog); ``None`` for a type with no full-page template (e.g. gbp_post).

    Also accepts a template key directly (``faq``, ``homepage``, ``service_area``), so
    a captured page type that is not one of the four JOB types still resolves to its
    audited sequence rather than to nothing."""
    key = _normalize_page_type(page_type)
    mapped = _PAGE_TYPE_TEMPLATE.get(key, "")
    if mapped:
        return TEMPLATES.get(mapped)
    return TEMPLATES.get(key)


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
    {
        "trust_bar", "map", "gallery", "search", "hours", "contact", "lead_form",
        "stats", "reviews",
        # The site's own furniture. Theme- and plugin-supplied on every page, so a
        # generated page must never be asked to write it. `app.modules.site_builder`
        # reached the same conclusion independently with its own `_CHROME_ROLES =
        # {"header", "nav", "footer"}`; that set now imports from here so the two
        # cannot disagree about what chrome is.
        "header", "nav", "footer", "breadcrumbs", "sidebar",
    }
)

#: The subset of :data:`_CHROME_KINDS` that is the SITE's furniture rather than a
#: content block the theme happens to own. Exported because `site_builder` filters on
#: exactly this when it builds a DesignIR from a measured capture.
CHROME_ROLES: frozenset[str] = frozenset({"header", "nav", "footer", "breadcrumbs", "sidebar"})



def _count(value: Any, *, maximum: int = 200) -> int:
    """A non-negative measured count, or 0 when absent/unusable.

    Bounded: a measurement of 400 cards is a bad capture, not a design, and passing it
    to a generator as a budget would be worse than having no budget at all.

    ``maximum`` exists because these are not all the same UNIT. One shared cap of 200
    was applied to item counts AND character budgets alike, so every section whose
    body copy ran past 200 characters - which is nearly every real section - had its
    measured budget silently rewritten to 0, i.e. "never measured". The generator
    then wrote to no budget at all and the capture looked empty rather than wrong.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n <= maximum else 0


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
        # Accepts either spelling: the measured profile emits camelCase (it is a wire
        # shape), a template or a hand-written blueprint uses snake_case.
        # Units differ, so the bounds do: repeated items are a small count, while
        # the char budgets are page copy (a 600-character services blurb is normal).
        max_items=_count(
            d.get("items") or d.get("max_items") or d.get("maxItems"), maximum=64
        ),
        heading_chars=_count(
            d.get("headingChars") or d.get("heading_chars"), maximum=512
        ),
        body_chars=_count(d.get("bodyChars") or d.get("body_chars"), maximum=8192),
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
#: Below this many sections, a "measured" blueprint is read as a FAILED CAPTURE rather
#: than as a design, and the audited template is used instead.
#:
#: MEASURED ON A REAL CLIENT: hudamoji.pk's homepage came back as exactly two sections -
#: a hero and a CTA - because the analyzer read a page builder's outer wrapper instead of
#: the sections inside it. No real homepage is a hero followed by a contact form, so that
#: is not a design system; it is a measurement that failed and said nothing about failing.
#: Trusting it would have published two-section pages for a client whose template calls
#: for seven, and the operator's only clue would be the page itself.
#:
#: Four is the floor because three is a shape a real page can genuinely have (hero, body,
#: CTA - a thin landing page), and refusing a design a client actually has is worse than
#: accepting a poor one. The bar is "could this plausibly be a page", not "is this good".
_MIN_MEASURED_SECTIONS = 4


def _plausible(sections: list[SectionSpec]) -> list[SectionSpec]:
    """The measurement, or ``[]`` when it is too thin to be a real page (see above)."""
    return sections if len(sections) >= _MIN_MEASURED_SECTIONS else []


def blueprint_for_page_type(layout: dict[str, Any], page_type: str) -> list[SectionSpec]:
    """The measured sections for THIS page type, from a profile's ``layout``, or ``[]``.

    Reads the per-page-type map (``layout.blueprints``, migration 0154) first, then
    falls back to the singular ``layout.blueprint`` ONLY when the profile says that
    capture was of this same page type (``layout.source_page_type``). A homepage
    measurement is evidence about homepages, and treating it as evidence about blog
    posts is the defect this function exists to prevent.

    A measurement too thin to be a real page is discarded (see
    :data:`_MIN_MEASURED_SECTIONS`) so the caller falls through to the audited template -
    a failed capture must not outrank a template that was designed.

    Matching is on the normalised page type, so ``"Service"``, ``"service"`` and
    ``" SERVICE "`` are one key.
    """
    wanted = _normalize_page_type(page_type)
    if not wanted:
        return []
    by_type = _as_dict(layout.get("blueprints"))
    for key, value in by_type.items():
        if _normalize_page_type(str(key)) == wanted:
            sections = _plausible(sections_from_raw(value))
            if sections:
                return sections
    # The singular blueprint counts for its OWN type only. A capture that never said
    # what it measured cannot claim to be this page type.
    if _normalize_page_type(str(layout.get("source_page_type") or "")) == wanted:
        return _plausible(sections_from_raw(layout.get("blueprint")))
    return []


def resolve_blueprint(
    *,
    design_profile: dict[str, Any] | None,
    template: str | None,
    page_type: str,
) -> list[SectionSpec]:
    """The ONE effective ordered blueprint a job's page is built to, by precedence:

    1. the client's MEASURED sections FOR THIS PAGE TYPE (``layout.blueprints[type]``,
       or the singular ``layout.blueprint`` when the capture was of this type);
    2. else an explicitly chosen TEMPLATE (one of the 7);
    3. else the DEFAULT template for this page type (service / local / blog / ...);
    4. else the client's measured sections for ANY page type - better than nothing
       when the page type has no template at all;
    5. else the analyzed ``layout.section_order`` (names only -> default layouts);
    6. else ``[]`` - nothing to shape by (the publish path keeps its plain behaviour).

    THE MEASURED DESIGN WINS - FOR THE PAGE TYPE IT WAS MEASURED ON. Tier 1 used to
    be "the analyzed blueprint", full stop, which is why this needed fixing: a client
    whose captured page was their homepage had the homepage's section sequence used as
    the structure of their blog articles and location pages. The sequence is the one
    part of a design system that is page-type-specific - hero, trust bar, services
    grid, stats, CTA is a correct homepage and a wrong blog post - so a measurement of
    one type does not transfer to another. Tiers 2 and 3 now sit above a foreign-type
    measurement precisely because the audited template for "blog" beats this client's
    homepage at being a blog post.

    WHAT DID NOT CHANGE, and must not: the rest of the design system - palette,
    typography, components, spacing - is NOT page-type-specific and is applied at
    every tier by the publish path, so pages still look like one developer built them
    whichever tier supplied their structure. And the 2026-09-17 owner decision that
    put measurement above the wizard's always-sent template still holds for the type
    actually measured, which is the case it was about.

    Returns a list of :class:`SectionSpec` (possibly empty). Degrade-safe: a
    malformed / unknown input at any tier falls through to the next.
    """
    profile = _as_dict(design_profile)
    layout = _as_dict(profile.get("layout"))

    measured = blueprint_for_page_type(layout, page_type)
    if measured:
        return measured
    chosen = get_template(template)
    if chosen is not None:
        return list(chosen.sections)
    default = template_for_page_type(page_type)
    if default is not None:
        return list(default.sections)
    # No template exists for this page type (an uncatalogued type like `gbp_post`).
    # Here a foreign-type measurement genuinely is the best available grounding - it
    # is at least this client's own site - so it is used rather than nothing.
    any_measured = sections_from_raw(layout.get("blueprint"))
    if any_measured:
        return any_measured
    for value in _as_dict(layout.get("blueprints")).values():
        sections = sections_from_raw(value)
        if sections:
            return sections
    from_order = sections_from_raw(layout.get("section_order"))
    if from_order:
        return from_order
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


def capacity_brief(specs: list[SectionSpec]) -> str:
    """The blueprint's CAPACITY as a line-per-section brief a generator can be given.

    WHY A BRIEF AND NOT JUST A VALIDATOR. Enforcing capacity only after the draft
    exists means regenerating, which costs a second call and usually produces copy that
    reads like it was cut to length - because it was. Telling the writer up front that
    the pricing section holds exactly three cards and the hero headline has about eight
    words of room is the cheap half of the fix, and the validator then has almost
    nothing left to catch.

    Only MEASURED facts appear. A section whose capacity was never measured contributes
    nothing rather than a zero, because "this section holds 0 items" is a different and
    false claim - and a generator handed it would write nothing at all.

    Returns "" when nothing about the blueprint was measured, which the caller should
    treat as "no design constraints known" and fall back to its own judgement.
    """
    lines: list[str] = []
    for index, spec in enumerate(specs, start=1):
        if not spec.content or not spec.has_capacity:
            continue
        parts: list[str] = []
        if spec.max_items:
            parts.append(
                f"exactly {spec.max_items} item{'s' if spec.max_items != 1 else ''}"
            )
        if spec.heading_chars:
            parts.append(f"heading up to about {spec.heading_chars} characters")
        if spec.body_chars:
            parts.append(f"body up to about {spec.body_chars} characters")
        if parts:
            lines.append(f"{index}. {spec.kind} ({spec.layout}): " + "; ".join(parts))
    if not lines:
        return ""
    return (
        "The page this copy is for has a MEASURED layout. Write to it - these are "
        "capacities, not suggestions, and copy that overflows is cut rather than "
        "given more room:\n" + "\n".join(lines)
    )


def overflowing(spec: SectionSpec, item_count: int) -> bool:
    """Whether ``item_count`` exceeds what this section was measured to hold.

    An UNMEASURED section never overflows: 0 means "not measured", and treating it as a
    limit would refuse every section on a page nobody analysed.
    """
    return bool(spec.max_items) and item_count > spec.max_items
