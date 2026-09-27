"""A design system knows a blog post is not a homepage (migration 0154).

THE DEFECT. ``brand_kits.blueprint`` was ONE ordered section list, and the resolver
returned it for EVERY page type. So a client whose captured page was their homepage had
the homepage's sequence - hero, trust bar, services grid, stats, testimonials, CTA - used
verbatim as the structure of their blog articles and location pages. Palette, typography
and components transferred correctly; the STRUCTURE did not, because a single blueprint
cannot express a per-page-type structure and nothing asked it to.

Three pieces make the fix, and this file covers the two that are pure:

* the CLASSIFIER that answers what kind of page a captured URL is, and answers ''
  rather than guessing - because a guess is stored as fact and would reshape every page
  of the type it guessed;
* the per-page-type MAP that the kit stores and the resolver reads.

The resolver's own precedence lives in ``test_page_blueprints.py``; the kit's
merge-forward write is a DB behaviour and is covered by
``tests/integration/test_content_planning_store.py``.
"""

from __future__ import annotations

import pytest

from app.services.page_blueprints import TEMPLATES, blueprint_for_page_type, resolve_blueprint
from app.services.site_design import classify_captured_page_type

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The classifier: answer, or say nothing.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com", "homepage"),
        ("https://acme.com/", "homepage"),
        ("https://acme.com/services", "service"),
        ("https://acme.com/services/drain-cleaning", "service"),
        ("https://acme.com/what-we-do", "service"),
        ("https://acme.com/locations/austin", "local"),
        ("https://acme.com/service-area", "service_area"),
        ("https://acme.com/areas-we-serve", "service_area"),
        ("https://acme.com/locations", "local"),
        ("https://acme.com/blog", "blog"),
        ("https://acme.com/blog/winter-tips", "blog"),
        ("https://acme.com/news/2026/update", "blog"),
        ("https://acme.com/faq", "faq"),
    ],
)
def test_the_url_path_classifies_the_captured_page(url: str, expected: str) -> None:
    assert classify_captured_page_type(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.com/about",
        "https://acme.com/team/jane",
        "https://acme.com/x/y/z",
        "https://acme.com/contact-us-today",
        "",
        "not a url at all",
    ],
)
def test_an_unclear_path_answers_nothing_rather_than_guessing(url: str) -> None:
    """'' IS the answer, and it is the safe one: an unkeyed sequence is never applied as
    per-type evidence, so an unclear URL costs nothing. A guess is stored as fact."""
    assert classify_captured_page_type(url) in ("", "homepage")
    if url.strip() and "/" in url.split("//", 1)[-1]:
        assert classify_captured_page_type(url) == ""


def test_a_service_page_under_a_location_path_is_still_a_service_page() -> None:
    """Ordering matters: "/services/austin-drain-cleaning" contains a location word and
    is a service page."""
    assert classify_captured_page_type("https://acme.com/services/austin-drain") == "service"


# --------------------------------------------------------------------------- #
# The per-page-type lookup.
# --------------------------------------------------------------------------- #
def test_the_map_is_read_for_the_requested_type() -> None:
    # FOUR SECTIONS, NOT TWO. A measurement thinner than four is read as a FAILED
    # CAPTURE rather than as a design and loses to the audited template
    # (`page_blueprints._MIN_MEASURED_SECTIONS`) - measured on a real kit that came
    # back as hero + CTA because the analyzer read a page builder's wrapper. This
    # test is about WHICH measurement is read for which page type, so its fixture has
    # to be a page a site could actually have.
    layout = {"blueprints": {"service": [
        {"kind": "hero"}, {"kind": "services"}, {"kind": "pricing"}, {"kind": "cta"},
    ]}}
    specs = blueprint_for_page_type(layout, "service")
    assert [s.kind for s in specs] == ["hero", "services", "pricing", "cta"]


def test_the_map_does_not_answer_for_a_different_type() -> None:
    layout = {"blueprints": {"homepage": [{"kind": "hero"}, {"kind": "stats"}]}}
    assert blueprint_for_page_type(layout, "blog") == []


def test_the_singular_blueprint_counts_only_for_its_own_recorded_type() -> None:
    layout = {
        "blueprint": [
            {"kind": "hero"}, {"kind": "services"}, {"kind": "stats"}, {"kind": "cta"},
        ],
        "source_page_type": "homepage",
    }
    assert [s.kind for s in blueprint_for_page_type(layout, "homepage")] == [
        "hero", "services", "stats", "cta",
    ]
    assert blueprint_for_page_type(layout, "blog") == []


def test_a_singular_blueprint_with_no_recorded_type_is_not_per_type_evidence() -> None:
    """Every kit written before 0154 is in this state. They must keep working - via the
    templates - and must not be treated as evidence about a type nobody recorded."""
    layout = {"blueprint": [{"kind": "hero"}, {"kind": "stats"}]}
    assert blueprint_for_page_type(layout, "homepage") == []
    assert blueprint_for_page_type(layout, "blog") == []


def test_an_empty_page_type_matches_nothing() -> None:
    layout = {"blueprints": {"service": [{"kind": "hero"}]}}
    assert blueprint_for_page_type(layout, "") == []


def test_the_map_wins_over_the_singular_blueprint_for_the_same_type() -> None:
    """The map is the newer, richer representation; the singular field is the legacy
    one carried for back-compat."""
    # Both shapes carry four sections: under four, a measurement is read as a failed
    # capture and discarded, which would make this test pass for the wrong reason.
    layout = {
        "blueprint": [
            {"kind": "hero"}, {"kind": "services"}, {"kind": "stats"}, {"kind": "cta"},
        ],
        "source_page_type": "service",
        "blueprints": {"service": [
            {"kind": "hero"}, {"kind": "features"}, {"kind": "pricing"}, {"kind": "cta"},
        ]},
    }
    assert [s.kind for s in blueprint_for_page_type(layout, "service")] == [
        "hero", "features", "pricing", "cta"
    ]


# --------------------------------------------------------------------------- #
# The behaviour an operator actually sees.
# --------------------------------------------------------------------------- #
def test_capturing_only_the_homepage_leaves_other_types_on_their_audited_template() -> None:
    """THE headline behaviour change. One capture of a homepage no longer dictates the
    structure of blog, service and location pages - each gets the sequence audited for
    its own kind, while palette/typography/components still come from the kit."""
    kit_layout = {
        "blueprint": [{"kind": "hero"}, {"kind": "trust_bar"}, {"kind": "stats"}, {"kind": "cta"}],
        "source_page_type": "homepage",
    }
    profile = {"layout": kit_layout}
    for page_type, template in (("service", "service"), ("blog", "blog"), ("local", "local")):
        specs = resolve_blueprint(design_profile=profile, template=None, page_type=page_type)
        assert [s.kind for s in specs] == [s.kind for s in TEMPLATES[template].sections], page_type


def test_capturing_a_second_page_type_makes_that_type_use_the_real_structure() -> None:
    """Why the map accumulates: capture the homepage, then the services page, and
    service pages start being built to the client's OWN service structure."""
    profile = {
        "layout": {
            "blueprint": [{"kind": "hero"}, {"kind": "stats"}],
            "source_page_type": "homepage",
            "blueprints": {
                "homepage": [{"kind": "hero"}, {"kind": "stats"}],
                "service": [{"kind": "hero"}, {"kind": "process"}, {"kind": "pricing"},
                            {"kind": "cta"}],
            },
        }
    }
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="service")
    assert [s.kind for s in specs] == ["hero", "process", "pricing", "cta"]
    # ...and the untouched types still fall to their templates.
    blog = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in blog] == [s.kind for s in TEMPLATES["blog"].sections]


def test_a_kit_written_before_0154_still_produces_a_usable_blueprint() -> None:
    """No backfill required: an old kit has no `blueprints` and no `source_page_type`,
    and every page type still resolves to something real."""
    profile = {"layout": {"blueprint": [{"kind": "hero"}, {"kind": "cta"}]}}
    for page_type in ("service", "blog", "local"):
        assert resolve_blueprint(design_profile=profile, template=None, page_type=page_type)


def test_the_design_tokens_are_not_page_type_scoped() -> None:
    """The half that must NOT change: palette / typography / components are one design
    system for the whole site, so pages still look like one developer built them
    whichever tier supplied their structure. The resolver only ever returns SECTIONS -
    it cannot express or drop a token - so this is a statement about the profile shape.
    """
    profile = {
        "palette": {"primary": "#0a0a0a"},
        "typography": {"heading_font": "Poppins"},
        "components": {"button_style": "solid pill"},
        "layout": {"blueprint": [{"kind": "hero"}], "source_page_type": "homepage"},
    }
    # A blog page falls to the template for its structure...
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["blog"].sections]
    # ...and the tokens are untouched, still there for the publish path to apply.
    assert profile["palette"]["primary"] == "#0a0a0a"
    assert profile["typography"]["heading_font"] == "Poppins"
    assert profile["components"]["button_style"] == "solid pill"
