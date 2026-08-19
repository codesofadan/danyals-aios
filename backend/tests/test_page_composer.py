"""Unit gate for the RICH Elementor page composer (``elementor.build_elementor_data``
with a ``blueprint``): the draft's content is SLOTTED into the blueprint's sections and
each is rendered as a classic, editable Elementor component (hero, icon-box grid,
accordion FAQ, testimonial cards, CTA banner). Proves the tree is valid, the content
lands in the RIGHT section by kind, and the profile palette/fonts are applied.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.elementor import build_elementor_data, elementor_json
from app.services.page_blueprints import TEMPLATES

pytestmark = pytest.mark.unit


_DRAFT = (
    "# Emergency Plumbing in Denver\n\n"
    "We fix burst pipes fast, any hour of the day or night.\n\n"
    "An extra intro line about our Denver team.\n\n"
    "## Why choose Acme\n\n"
    "- **Fast response** - on-site within 60 minutes\n"
    "- **Licensed** - fully insured master plumbers\n"
    "- **Upfront pricing** - no surprise fees\n\n"
    "## How it works\n\n"
    "- Call our 24/7 line\n"
    "- We dispatch the nearest van\n"
    "- We fix it and clean up\n\n"
    "## Frequently asked questions\n\n"
    "### Do you charge for callouts?\n\n"
    "No, every quote is free.\n\n"
    "### Are you available at night?\n\n"
    "Yes, 24/7 including holidays.\n\n"
    "## Ready to book?\n\n"
    "Call Acme today for fast, reliable service.\n"
)

_CTA = {
    "heading": "Ready to fix it?",
    "text": "Talk to Acme about your emergency today.",
    "button_label": "Get in touch",
    "button_url": "https://acme.test",
}
_PROFILE = {
    "palette": {"primary": "#0a0a0a", "secondary": "#333", "background": "#fffbea",
                "text": "#111", "accent": "#ff5500"},
    "typography": {"heading_font": "Poppins, sans-serif", "body_font": "Inter, sans-serif",
                   "base_size": "18px"},
    "layout": {"container_width": "1080px", "hero_style": "split"},
    "components": {"button_style": "solid pill", "card_style": "soft shadow",
                   "spacing_scale": "spacious"},
}


def _blueprint(name: str) -> list[dict[str, Any]]:
    return [s.as_dict() for s in TEMPLATES[name].sections]


def _all_elements(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every element with an ``elType`` anywhere in the tree (sections, inner-sections,
    columns, widgets) - the composer nests inner-sections inside columns for grids."""
    out: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        out.append(node)
        for child in node.get("elements", []):
            walk(child)

    for section in tree:
        walk(section)
    return out


def _widgets(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _all_elements(tree) if e.get("elType") == "widget"]


def _sections_by_class(tree: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [
        s for s in tree
        if str(s.get("settings", {}).get("_css_classes", "")).startswith(prefix)
    ]


def test_rich_tree_is_structurally_valid() -> None:
    tree = build_elementor_data(_DRAFT, design_profile=_PROFILE, blueprint=_blueprint("service"),
                                cta=_CTA, testimonials=["Acme saved our basement! - a happy client"])
    assert isinstance(tree, list) and tree
    for element in _all_elements(tree):
        assert element["elType"] in {"section", "column", "widget"}
        if element["elType"] == "widget":
            assert element["widgetType"] in {
                "heading", "text-editor", "image", "button", "icon-box", "icon-list", "accordion",
            }
    # Deterministic + unique ids across the whole tree.
    ids = [e["id"] for e in _all_elements(tree)]
    assert len(ids) == len(set(ids))
    # Deterministic: same inputs -> byte-identical tree.
    again = build_elementor_data(_DRAFT, design_profile=_PROFILE, blueprint=_blueprint("service"),
                                 cta=_CTA, testimonials=["Acme saved our basement! - a happy client"])
    assert json.dumps(tree) == json.dumps(again)
    # elementor_json round-trips.
    assert json.loads(
        elementor_json(_DRAFT, _PROFILE, blueprint=_blueprint("service"), cta=_CTA,
                       testimonials=["Acme saved our basement! - a happy client"])
    ) == tree


def test_hero_carries_title_and_cta_button() -> None:
    tree = build_elementor_data(_DRAFT, blueprint=_blueprint("service"), cta=_CTA)
    hero = _sections_by_class(tree, "aios-hero")
    assert hero, "a hero section is present"
    hero_widgets = _widgets([hero[0]])
    h1 = next(w for w in hero_widgets if w["widgetType"] == "heading")
    assert h1["settings"]["title"] == "Emergency Plumbing in Denver"
    assert h1["settings"]["header_size"] == "h1"
    # The primary CTA button rides in the hero.
    assert any(w["widgetType"] == "button" for w in hero_widgets)


def test_benefits_render_as_an_icon_box_grid() -> None:
    tree = build_elementor_data(_DRAFT, blueprint=_blueprint("service"), cta=_CTA)
    benefits = _sections_by_class(tree, "aios-benefits")
    assert benefits, "the 'Why choose Acme' block slotted into the benefits section"
    assert "aios-layout-grid" in benefits[0]["settings"]["_css_classes"]
    boxes = [w for w in _widgets([benefits[0]]) if w["widgetType"] == "icon-box"]
    assert len(boxes) == 3, "one icon-box card per bullet"
    titles = {b["settings"]["title_text"] for b in boxes}
    assert "Fast response" in titles and "Licensed" in titles


def test_process_renders_as_a_numbered_step_list() -> None:
    tree = build_elementor_data(_DRAFT, blueprint=_blueprint("service"), cta=_CTA)
    process = _sections_by_class(tree, "aios-process")
    assert process, "the 'How it works' block slotted into the process section"
    lists = [w for w in _widgets([process[0]]) if w["widgetType"] == "icon-list"]
    assert lists and len(lists[0]["settings"]["icon_list"]) == 3
    assert "Step 1." in lists[0]["settings"]["icon_list"][0]["text"]


def test_faq_slots_into_the_faq_accordion_by_kind() -> None:
    # The FAQ block is NOT positionally aligned with the faq section, yet it lands there.
    tree = build_elementor_data(_DRAFT, blueprint=_blueprint("service"), cta=_CTA)
    faq = _sections_by_class(tree, "aios-faq")
    assert faq, "a faq section is present"
    accordions = [w for w in _widgets([faq[0]]) if w["widgetType"] == "accordion"]
    assert accordions, "the FAQ is an accordion"
    tabs = accordions[0]["settings"]["tabs"]
    assert [t["tab_title"] for t in tabs] == ["Do you charge for callouts?", "Are you available at night?"]


def test_cta_is_a_banner_with_accent_background() -> None:
    tree = build_elementor_data(_DRAFT, design_profile=_PROFILE, blueprint=_blueprint("service"), cta=_CTA)
    cta = _sections_by_class(tree, "aios-cta")
    assert cta and "aios-layout-banner" in cta[0]["settings"]["_css_classes"]
    assert cta[0]["settings"]["background_color"] == "#ff5500"  # palette accent
    assert any(w["widgetType"] == "button" for w in _widgets([cta[0]]))


def test_testimonials_render_from_the_supplied_list() -> None:
    quotes = ["They were fast and fair. - Dana", "Saved our basement at 2am. - Mike"]
    tree = build_elementor_data(_DRAFT, blueprint=_blueprint("service"), cta=_CTA, testimonials=quotes)
    testi = _sections_by_class(tree, "aios-testimonials")
    assert testi, "a testimonials section rendered from the supplied quotes"
    editors = " ".join(
        w["settings"].get("editor", "") for w in _widgets([testi[0]]) if w["widgetType"] == "text-editor"
    )
    assert "Dana" in editors and "Mike" in editors


def test_profile_palette_and_fonts_are_applied() -> None:
    tree = build_elementor_data(_DRAFT, design_profile=_PROFILE, blueprint=_blueprint("service"), cta=_CTA)
    headings = [w for w in _widgets(tree) if w["widgetType"] == "heading"]
    assert any(w["settings"].get("title_color") == "#0a0a0a" for w in headings)  # palette primary
    assert any(w["settings"].get("typography_font_family") == "Poppins, sans-serif" for w in headings)


def test_blog_body_absorbs_the_article_h2_blocks() -> None:
    draft = (
        "# The 2026 Guide to X\n\nA hook intro.\n\n"
        "## First point\n\nBody about the first point.\n\n"
        "## Second point\n\nBody about the second point.\n\n"
        "## Third point\n\nBody about the third point.\n"
    )
    tree = build_elementor_data(draft, blueprint=_blueprint("blog"), cta=_CTA)
    body = _sections_by_class(tree, "aios-body")
    assert body, "a body section holds the article's H2 blocks"
    text = " ".join(
        w["settings"].get("title", "") + w["settings"].get("editor", "")
        for w in _widgets(body)
    )
    # No generated H2 block is dropped - all three points land in the body.
    assert "First point" in text and "Second point" in text and "Third point" in text


def test_section_image_renders_inside_its_own_section_not_bunched() -> None:
    # An image sitting in a grid section's markdown (as ![alt](url)) renders as an image
    # widget INSIDE that section - not dropped, not bunched at the top of the page.
    draft = (
        "# Emergency Plumbing in Denver\n\n"
        "![a burst pipe being repaired](https://cdn.test/hero.png)\n\n"
        "We fix burst pipes fast.\n\n"
        "## Why choose Acme\n\n"
        "![a licensed plumber at work](https://cdn.test/benefits.png)\n\n"
        "- **Fast** - on-site in 60 minutes\n"
        "- **Licensed** - insured pros\n"
        "- **Upfront** - no surprise fees\n"
    )
    tree = build_elementor_data(draft, blueprint=_blueprint("service"), cta=_CTA)
    hero = _sections_by_class(tree, "aios-hero")[0]
    benefits = _sections_by_class(tree, "aios-benefits")[0]
    hero_imgs = [w["settings"]["image"]["url"] for w in _widgets([hero]) if w["widgetType"] == "image"]
    benefit_imgs = [w["settings"]["image"]["url"] for w in _widgets([benefits]) if w["widgetType"] == "image"]
    assert hero_imgs == ["https://cdn.test/hero.png"]        # hero image in the hero
    assert benefit_imgs == ["https://cdn.test/benefits.png"]  # section image in ITS section
    # The benefits section still renders its grid cards alongside the image.
    assert any(w["widgetType"] == "icon-box" for w in _widgets([benefits]))


def test_empty_draft_still_yields_a_valid_tree() -> None:
    tree = build_elementor_data("", blueprint=_blueprint("service"), cta=None)
    assert isinstance(tree, list) and tree
    assert all(e["elType"] in {"section", "column", "widget"} for e in _all_elements(tree))


# --------------------------------------------------------------------------- #
# Worker wiring: a job that picked a TEMPLATE (no analyzed site) still gets the rich,
# classic Elementor page - the template resolves the blueprint and the content is slotted.
# --------------------------------------------------------------------------- #
def test_worker_resolves_a_template_only_job_to_a_rich_tree() -> None:
    from workers.tasks.content import _plugin_payload, _resolve_row_blueprint

    row = {
        "code": "CJ-7001",
        "topic": "emergency plumbing in denver",
        "outline": {"meta": {"title": "Emergency Plumbing in Denver", "description": "Fast help."}},
        "keyword_map": {"primary": "emergency plumbing"},
        "page_type": "service",
        "source_pack": {"client_name": "Acme", "template": "service", "wp_site_url": "https://acme.test"},
    }
    # The template (not an analyzed profile) drives the blueprint.
    specs = _resolve_row_blueprint(row)
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["service"].sections]

    from app.config import Settings

    payload = _plugin_payload(
        row, _DRAFT, "Emergency Plumbing in Denver",
        settings=Settings(_env_file=None, app_env="dev", content_elementor_enabled=True),
    )
    tree = json.loads(payload["elementor_data"])
    classes = [str(s.get("settings", {}).get("_css_classes", "")) for s in tree]
    assert any(c.startswith("aios-hero") for c in classes)
    assert any(c.startswith("aios-benefits") for c in classes)   # grid slot
    assert any(c.startswith("aios-faq") for c in classes)        # accordion slot
    # There is an accordion widget (the FAQ) and an icon-box grid (benefits).
    kinds = {w["widgetType"] for w in _widgets(tree)}
    assert "accordion" in kinds and "icon-box" in kinds
