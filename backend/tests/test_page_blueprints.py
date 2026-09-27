"""Unit gate for the SHARED page-layout doctrine (``app.services.page_blueprints``):
the 7 named templates, the precedence-ordered blueprint resolver, the raw-section
coercion, and the two SYNC LOCKS that keep the doctrine single-sourced - the schema's
``PageTemplate`` literal must equal the module's template keys, and the committed skills
reference (``PAGE-TEMPLATES.md``) must equal the module's rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, get_args

import pytest

from app.schemas.content import PageTemplate
from app.services.page_blueprints import (
    LAYOUT_VARIANTS,
    TEMPLATES,
    PageBlueprint,
    get_template,
    render_markdown,
    resolve_blueprint,
    sections_from_raw,
    template_for_page_type,
    template_names,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE = _REPO_ROOT / ".claude" / "skills" / "_shared" / "reference" / "PAGE-TEMPLATES.md"

_EXPECTED = {
    "service", "location", "service_area", "blog", "faq", "local", "homepage",
    # An ABOUT page is a layout, not an article, and it was the one page type with no
    # wireframe of its own - so every "about us" page fell back to the blog template
    # and published as a wall of prose with a hero on top.
    "about",
}


def test_exactly_the_eight_named_templates() -> None:
    assert set(TEMPLATES) == _EXPECTED
    assert set(template_names()) == _EXPECTED
    assert len(template_names()) == 8


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_each_template_is_well_formed(name: str) -> None:
    bp = TEMPLATES[name]
    assert isinstance(bp, PageBlueprint)
    assert bp.template == name
    assert bp.sections, "a template has sections"
    # Audited invariants: hero is first, cta is the last content section, >=1 content.
    assert bp.sections[0].kind == "hero"
    content = [s for s in bp.sections if s.content]
    assert content, "a template has at least one content-bearing section"
    assert content[-1].kind == "cta", "the last CONTENT section is the CTA"
    # At most one absorb section; every layout variant is from the controlled vocab.
    assert sum(1 for s in bp.sections if s.absorb) <= 1
    for s in bp.sections:
        assert s.layout in LAYOUT_VARIANTS, f"{name}:{s.kind} has unknown layout {s.layout}"


def test_page_template_literal_matches_module() -> None:
    # The schema's PageTemplate literal is the wire contract; it must name EXACTLY the
    # module's template keys, or the dashboard/skills could send a template the resolver
    # cannot honour.
    assert set(get_args(PageTemplate)) == _EXPECTED


# --------------------------------------------------------------------------- #
# The resolver precedence: MEASURED design -> template -> thin section_order ->
# default -> nothing.
# --------------------------------------------------------------------------- #
_MEASURED = [
    {"kind": "hero", "layout": "split"},
    {"kind": "services", "layout": "grid"},
    {"kind": "proof", "layout": "carousel"},
    {"kind": "faq", "layout": "accordion"},
    {"kind": "cta", "layout": "banner"},
]


def test_the_measured_blueprint_wins_over_a_template_for_its_own_page_type() -> None:
    """The client's captured design is what pages OF THAT KIND are built to.

    Two decisions are pinned here, and they are not in tension.

    The measurement outranks the template (2026-09-17). Before that it was the
    reverse, and the consequence was total: the content flow sends a template on
    EVERY launch, so the "explicit template" tier matched every job and a client's
    analyzed design never shaped a single page. Re-inject by moving the
    ``get_template`` check back above the measured blueprint and this fails.

    And the measurement applies to the page type it was MEASURED ON (0154). A capture
    measures one page; a homepage's hero/services-grid/stats order is a correct
    homepage and a wrong blog post. So the profile has to say which type it measured -
    here, ``blog`` - for its sequence to be used on a blog page.
    """
    profile = {"layout": {"blueprint": _MEASURED, "source_page_type": "blog"}}
    specs = resolve_blueprint(design_profile=profile, template="faq", page_type="blog")
    assert [s.kind for s in specs] == ["hero", "services", "proof", "faq", "cta"]
    assert [s.kind for s in specs] != [s.kind for s in TEMPLATES["faq"].sections]


def test_a_blueprint_measured_on_another_page_type_does_not_shape_this_one() -> None:
    """THE 0154 defect. A client whose captured page was their HOMEPAGE had the
    homepage's section sequence used as the structure of their blog articles and
    location pages - palette and typography transferred correctly, the structure did
    not. A blog page now gets the audited blog template instead.

    Re-inject by returning ``layout.blueprint`` from tier 1 regardless of type and
    this fails.
    """
    profile = {"layout": {"blueprint": _MEASURED, "source_page_type": "homepage"}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["blog"].sections]


def test_a_capture_that_never_said_what_it_measured_is_not_per_type_evidence() -> None:
    """Empty is the safe answer, not a guess: an unkeyed sequence is never applied as
    evidence about a page type, so a capture whose URL gave nothing away cannot
    reshape the wrong pages."""
    profile = {"layout": {"blueprint": _MEASURED}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["blog"].sections]


def test_the_per_page_type_map_is_read_before_the_singular_blueprint() -> None:
    """The kit accumulates a sequence per captured type (0154), so an operator can
    capture the homepage and then the services page and have both used correctly."""
    profile = {
        "layout": {
            "blueprint": _MEASURED,
            "source_page_type": "homepage",
            "blueprints": {
                "service": [
                    {"kind": "hero"}, {"kind": "services"}, {"kind": "pricing"},
                    {"kind": "cta"},
                ],
            },
        }
    }
    service = resolve_blueprint(design_profile=profile, template="faq", page_type="service")
    assert [s.kind for s in service] == ["hero", "services", "pricing", "cta"]
    # ...and the homepage capture still shapes a homepage.
    home = resolve_blueprint(design_profile=profile, template=None, page_type="homepage")
    assert [s.kind for s in home] == ["hero", "services", "proof", "faq", "cta"]


def test_the_page_type_key_is_matched_case_and_separator_insensitively() -> None:
    """These values arrive from a job row, a kit's JSON and an operator's wizard, and
    those three have never agreed on case or on hyphen-vs-underscore."""
    measured = [
        {"kind": "hero"}, {"kind": "services"}, {"kind": "service_areas"}, {"kind": "cta"},
    ]
    profile = {"layout": {"blueprints": {"Service-Area": measured}}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="service_area")
    assert [s.kind for s in specs] == ["hero", "services", "service_areas", "cta"]


def test_five_measured_sections_resolve_to_exactly_five() -> None:
    """The owner's rule stated as a test: a design with five sections produces a
    five-section blueprint - not the template's count, not a truncation."""
    blueprint = [{"kind": k} for k in ("hero", "intro", "services", "proof", "cta")]
    specs = resolve_blueprint(
        design_profile={"layout": {"blueprint": blueprint, "source_page_type": "service"}},
        template="service",
        page_type="service",
    )
    assert len(specs) == 5


def test_measured_capacities_survive_the_resolver() -> None:
    """Capacity is the other half of conformance: matching a section sequence while
    overflowing every slot is not matching the design. These were measured and then
    dropped at the API wire model, so max_items was always 0 in production."""
    profile = {
        "layout": {
            "source_page_type": "service",
            "blueprint": [
                {"kind": "hero", "headingChars": 48, "bodyChars": 180},
                {"kind": "services", "items": 3, "bodyChars": 320},
                {"kind": "faq", "items": 5},
                {"kind": "cta"},
            ],
        }
    }
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="service")
    assert specs[0].heading_chars == 48
    assert specs[1].max_items == 3
    assert specs[1].body_chars == 320


def test_explicit_template_still_wins_over_a_thin_section_order() -> None:
    """A bare section_order carries names with no capacities - weaker grounding than
    a real template, so the template keeps this tier."""
    profile = {"layout": {"section_order": ["hero", "about", "cta"]}}
    specs = resolve_blueprint(design_profile=profile, template="faq", page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["faq"].sections]


def test_analyzed_blueprint_used_when_no_template() -> None:
    profile = {
        "layout": {
            "source_page_type": "service",
            "blueprint": [
                {"kind": "hero", "layout": "split"},
                {"kind": "services", "layout": "grid"},
                {"kind": "faq", "layout": "accordion"},
                {"kind": "cta", "layout": "banner"},
            ],
        }
    }
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="service")
    assert [s.kind for s in specs] == ["hero", "services", "faq", "cta"]
    assert specs[1].layout == "grid"


def test_a_foreign_type_measurement_is_used_when_the_type_has_no_template() -> None:
    """``gbp_post`` has no full-page template, so there is nothing better to fall back
    to and the client's own measured sequence beats returning nothing. This is the one
    tier where a foreign-type measurement is still the right answer."""
    profile = {
        "layout": {
            "blueprint": [{"kind": "hero"}, {"kind": "cta"}],
            "source_page_type": "homepage",
        }
    }
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="gbp_post")
    assert [s.kind for s in specs] == ["hero", "cta"]


def test_analyzed_section_order_used_when_the_page_type_has_no_template() -> None:
    """A bare ``section_order`` is the THINNEST grounding there is - names with no
    capacities and no page type - so it now sits below the page-type default
    template. It is still used where no template exists (``gbp_post``), which is the
    only place it is the best available answer."""
    profile = {"layout": {"section_order": ["hero", "faq", "cta"]}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="gbp_post")
    assert [s.kind for s in specs] == ["hero", "faq", "cta"]


def test_the_page_type_template_outranks_a_thin_section_order() -> None:
    profile = {"layout": {"section_order": ["hero", "faq", "cta"]}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["blog"].sections]


def test_page_type_default_when_no_template_or_profile() -> None:
    specs = resolve_blueprint(design_profile=None, template=None, page_type="service")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["service"].sections]
    assert resolve_blueprint(design_profile=None, template=None, page_type="local")
    assert resolve_blueprint(design_profile=None, template=None, page_type="blog")


def test_gbp_post_has_no_default_blueprint() -> None:
    # gbp_post is a compact GBP card, not a full page -> nothing to shape by (the publish
    # path keeps its plain behaviour).
    assert resolve_blueprint(design_profile=None, template=None, page_type="gbp_post") == []
    assert template_for_page_type("gbp_post") is None


def test_unknown_template_falls_through() -> None:
    assert get_template("not-a-template") is None
    specs = resolve_blueprint(design_profile=None, template="not-a-template", page_type="service")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["service"].sections]


# --------------------------------------------------------------------------- #
# Raw-section coercion (analyzed profiles arrive as dicts OR bare kind strings).
# --------------------------------------------------------------------------- #
def test_sections_from_raw_coerces_dicts_and_strings() -> None:
    raw = [
        "hero",
        {"kind": "services", "heading": "What we do", "layout": "grid"},
        {"name": "faq"},          # 'name' alias for kind
        {"heading": "no kind"},   # skipped: no kind
        42,                        # skipped: junk
    ]
    specs = sections_from_raw(raw)
    assert [s.kind for s in specs] == ["hero", "services", "faq"]
    assert specs[1].heading == "What we do" and specs[1].layout == "grid"
    # A chrome kind (trust_bar) defaults content=False; a body kind defaults content=True.
    assert sections_from_raw(["trust_bar"])[0].content is False
    assert sections_from_raw(["intro"])[0].content is True


def test_sections_from_raw_degrades_on_junk() -> None:
    assert sections_from_raw(None) == []
    assert sections_from_raw("not a list") == []
    assert sections_from_raw([{}, "", 0]) == []


# --------------------------------------------------------------------------- #
# The SKILLS reference doc is generated from THIS module (single source of truth).
# --------------------------------------------------------------------------- #
def test_skills_reference_markdown_is_in_sync() -> None:
    assert _REFERENCE.exists(), f"missing generated reference: {_REFERENCE}"
    committed = _REFERENCE.read_text(encoding="utf-8")
    assert committed == render_markdown(), (
        "PAGE-TEMPLATES.md is stale — regenerate with "
        "`python -m app.services.page_blueprints > <path>` (it drifted from the module)."
    )


# --------------------------------------------------------------------------- #
# CAPACITY. The blueprint used to say a page HAS a pricing section and not that it
# holds three cards, so a draft with seven plans was slotted in and the overflow
# absorbed - design-aware only about order. These carry the measurement.
# --------------------------------------------------------------------------- #
class TestCapacity:
    def test_measured_capacity_survives_the_raw_coercion(self) -> None:
        from app.services.page_blueprints import section_from_raw
        spec = section_from_raw(
            {"kind": "pricing", "layout": "grid", "items": 3,
             "headingChars": 42, "bodyChars": 180}
        )
        assert spec is not None
        assert (spec.max_items, spec.heading_chars, spec.body_chars) == (3, 42, 180)
        assert spec.has_capacity is True

    def test_both_spellings_are_accepted(self) -> None:
        """A stored profile is camelCase on the wire; a hand-written blueprint or a
        template uses snake_case. Accepting one silently drops the other."""
        from app.services.page_blueprints import section_from_raw
        a = section_from_raw({"kind": "pricing", "items": 3})
        b = section_from_raw({"kind": "pricing", "max_items": 3})
        assert a is not None and b is not None
        assert a.max_items == b.max_items == 3

    def test_an_unmeasured_section_reports_no_capacity(self) -> None:
        """0 means "not measured", NOT "holds nothing" - the distinction the whole
        feature turns on."""
        from app.services.page_blueprints import section_from_raw
        spec = section_from_raw({"kind": "pricing"})
        assert spec is not None
        assert spec.has_capacity is False
        assert spec.max_items == 0

    @pytest.mark.parametrize("bad", [0, -3, 9999, "many", None, {}])
    def test_an_implausible_count_is_refused(self, bad: object) -> None:
        """A "400 cards" reading is a bad capture, not a design. Passing it on as a
        budget would be worse than having none."""
        from app.services.page_blueprints import section_from_raw
        spec = section_from_raw({"kind": "pricing", "items": bad})
        assert spec is not None and spec.max_items == 0

    def test_overflow_is_measured_against_a_measured_limit_only(self) -> None:
        from app.services.page_blueprints import SectionSpec, overflowing
        measured = SectionSpec(kind="pricing", max_items=3)
        assert overflowing(measured, 7) is True
        assert overflowing(measured, 3) is False
        # An unmeasured section can never overflow, or every page nobody analysed
        # would be refused.
        assert overflowing(SectionSpec(kind="pricing"), 99) is False

    def test_the_brief_states_only_what_was_measured(self) -> None:
        from app.services.page_blueprints import SectionSpec, capacity_brief
        brief = capacity_brief([
            SectionSpec(kind="hero", heading_chars=48),
            SectionSpec(kind="pricing", layout="grid", max_items=3),
            SectionSpec(kind="about"),                      # unmeasured - contributes nothing
            SectionSpec(kind="map", content=False, max_items=9),  # chrome - not written to
        ])
        assert "exactly 3 items" in brief
        assert "48 characters" in brief
        # Assert on the LINES, not on substrings: "about" legitimately occurs in
        # the prose ("up to about 48 characters"), so a substring check for the
        # unmeasured `about` SECTION would test the wording, not the behaviour.
        numbered = [ln for ln in brief.splitlines() if ln[:1].isdigit()]
        kinds = [ln.split(" ", 1)[1].split(" (", 1)[0] for ln in numbered]
        assert kinds == ["hero", "pricing"], (
            "an unmeasured section and a chrome section both contribute nothing"
        )

    def test_a_wholly_unmeasured_blueprint_yields_no_brief(self) -> None:
        """Not an empty instruction - NO instruction. A generator handed "write to
        these capacities:" followed by nothing would be worse than being told nothing."""
        from app.services.page_blueprints import SectionSpec, capacity_brief
        assert capacity_brief([SectionSpec(kind="hero"), SectionSpec(kind="cta")]) == ""


# --------------------------------------------------------------------------- #
# A FAILED CAPTURE IS NOT A DESIGN. Measured on hudamoji.pk: the analyzer read a page
# builder's outer wrapper instead of the sections inside it and returned a homepage as
# exactly two sections, hero + CTA. Nothing in the profile said the measurement had
# failed, so it outranked the audited template and would have published two-section
# pages for a client whose template calls for seven.
# --------------------------------------------------------------------------- #
class TestThinMeasurement:
    _THIN: ClassVar[dict[str, Any]] = {
        "layout": {
            "source_page_type": "homepage",
            "blueprint": [{"kind": "hero", "layout": "centered"},
                          {"kind": "cta", "layout": "stacked"}],
        }
    }

    def test_a_two_section_measurement_loses_to_the_template(self) -> None:
        specs = resolve_blueprint(
            design_profile=self._THIN, template=None, page_type="homepage"
        )
        assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["homepage"].sections]

    def test_the_same_thin_shape_under_the_per_type_map_also_loses(self) -> None:
        profile = {"layout": {"blueprints": {"homepage": self._THIN["layout"]["blueprint"]}}}
        specs = resolve_blueprint(
            design_profile=profile, template=None, page_type="homepage"
        )
        assert len(specs) == 7

    def test_a_four_section_measurement_is_believed(self) -> None:
        """The bar is "could this plausibly be a page", not "is this a good page". A
        client whose real design is thin must still get their own design."""
        profile = {
            "layout": {
                "source_page_type": "homepage",
                "blueprint": ["hero", "services", "testimonials", "cta"],
            }
        }
        specs = resolve_blueprint(
            design_profile=profile, template=None, page_type="homepage"
        )
        assert [s.kind for s in specs] == ["hero", "services", "testimonials", "cta"]

    def test_a_thin_measurement_still_beats_nothing_when_no_template_exists(self) -> None:
        """`gbp_post` has no template of its own, so the client's own site - thin or not -
        is genuinely the best grounding available, and the fallback tiers keep it."""
        specs = resolve_blueprint(
            design_profile=self._THIN, template=None, page_type="gbp_post"
        )
        assert [s.kind for s in specs] == ["hero", "cta"]
