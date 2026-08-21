"""Unit gate for the Gutenberg renderer (``app.services.gutenberg``): the SAME
edited :class:`PageModel` that renders to styled HTML and to an Elementor tree also
renders to native WordPress block markup - proper individual blocks (heading /
paragraph / list / image / button / quote / group), never one giant HTML blob.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.editor_mode import resolve_editor_mode
from app.services.gutenberg import model_to_gutenberg
from app.services.page_model import build_page_model

pytestmark = pytest.mark.unit

_DRAFT = (
    "# Automate the busywork\n\n"
    "We deploy AI agents and automations for businesses worldwide.\n\n"
    "## Why choose us\n\n"
    "- **Fast** - weeks not quarters\n"
    "- **Agents** - real agents, not chatbots\n"
    "- **Integrated** - built on your tools\n\n"
    "## How it works\n\n"
    "- We audit your workflows\n"
    "- We build the automations\n\n"
    "## Frequently asked questions\n\n"
    "### How fast can we go live?\n\nAbout two weeks.\n\n"
    "### Is our data safe?\n\nYes, always.\n\n"
    "## Ready to go?\n\nBook a discovery call.\n"
)
_CTA = {"heading": "Ready to automate?", "text": "Book a call.", "button_label": "Book", "button_url": "#"}


def _model_dict() -> dict[str, Any]:
    model = build_page_model(
        _DRAFT, design_profile=None, template=None, page_type="service", cta=_CTA,
        testimonials=["Best decision we made.", "Fast and reliable."], title="Automate",
    )
    return model.to_dict()


def test_output_is_real_blocks_not_one_html_blob() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert "<!-- wp:heading" in markup
    assert "<!-- wp:paragraph" in markup
    assert "<!-- wp:list" in markup
    # every opened block comment is closed - proper block boundaries, not a single dump
    assert markup.count("<!-- wp:") == markup.count("<!-- /wp:")


def test_hero_becomes_an_h1_heading_block() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert '<!-- wp:heading {"level":1}' in markup or '"level":1' in markup
    assert "Automate the busywork" in markup


def test_faq_pairs_become_heading_plus_paragraph_pairs() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert "How fast can we go live?" in markup
    assert "About two weeks." in markup


def test_testimonials_become_quote_blocks() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert "<!-- wp:quote -->" in markup
    assert "Best decision we made." in markup


def test_cta_becomes_a_button_block() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert "<!-- wp:buttons -->" in markup
    assert 'href="#"' in markup
    assert "Book" in markup


def test_sections_carry_the_shared_aios_css_classes() -> None:
    """The SAME classes the HTML + Elementor renderers use, so existing design_css
    keeps styling a Gutenberg-rendered page with no new CSS."""
    markup = model_to_gutenberg(_model_dict())
    assert "aios-hero" in markup
    assert "aios-faq" in markup


def test_hidden_sections_never_render() -> None:
    model = build_page_model(
        "# Just a title\n\nOne paragraph.\n", design_profile=None, template="service",
        page_type="service", cta=None, testimonials=[], title="T",
    )
    d = model.to_dict()
    hidden_kinds = {s["kind"] for s in d["sections"] if not s["visible"]}
    assert hidden_kinds  # the service template has unfilled chrome sections
    markup = model_to_gutenberg(d)
    for kind in hidden_kinds:
        assert f"aios-{kind}" not in markup


def test_empty_model_still_yields_valid_non_empty_markup() -> None:
    markup = model_to_gutenberg({"title": "", "sections": [], "design": {}})
    assert markup.strip()
    assert markup.count("<!-- wp:") == markup.count("<!-- /wp:")


def test_grid_sections_become_columns_of_heading_and_paragraph() -> None:
    markup = model_to_gutenberg(_model_dict())
    assert "<!-- wp:columns -->" in markup
    assert "<!-- wp:column -->" in markup
    assert "Fast" in markup


# --------------------------------------------------------------------------- #
# resolve_editor_mode
# --------------------------------------------------------------------------- #
def test_elementor_mode_falls_back_to_gutenberg_when_unavailable() -> None:
    assert resolve_editor_mode("elementor", elementor_available=False) == "gutenberg"
    assert resolve_editor_mode("elementor", elementor_available=True) == "elementor"


def test_auto_prefers_elementor_when_available_else_gutenberg() -> None:
    assert resolve_editor_mode("auto", elementor_available=True) == "elementor"
    assert resolve_editor_mode("auto", elementor_available=False) == "gutenberg"


def test_gutenberg_and_hybrid_and_unknown_all_resolve_to_gutenberg() -> None:
    assert resolve_editor_mode("gutenberg", elementor_available=True) == "gutenberg"
    assert resolve_editor_mode("hybrid", elementor_available=True) == "gutenberg"
    assert resolve_editor_mode("something-unknown", elementor_available=True) == "gutenberg"
