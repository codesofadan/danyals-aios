"""Unit gate for the canonical editable PAGE MODEL (``app.services.page_model``): the
draft is slotted ONCE into typed, editable sections; the model round-trips through its
dict form (what the dashboard editor loads + saves); and it renders to premium,
self-contained styled HTML (the preview == published surface).
"""

from __future__ import annotations

import pytest

from app.services.page_model import build_page_model, model_to_html, page_model_from_dict

pytestmark = pytest.mark.unit

_DRAFT = (
    "# Automate the busywork\n\n"
    "We deploy AI agents and automations for businesses worldwide.\n\n"
    "An extra intro line.\n\n"
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


def _kinds(model: object) -> dict[str, bool]:
    return {s.kind: s.visible for s in model.sections}  # type: ignore[attr-defined]


def test_content_slots_into_the_right_sections() -> None:
    m = build_page_model(_DRAFT, design_profile=None, template="service", page_type="service",
                         cta=_CTA, testimonials=["Loved it. - A client"], title="X")
    vis = _kinds(m)
    # The classified blocks land in the matching sections; chrome/unfilled -> hidden.
    assert vis["hero"] is True
    assert vis["benefits"] is True     # "Why choose us"
    assert vis["process"] is True      # "How it works"
    assert vis["faq"] is True          # FAQ pairs
    assert vis["testimonials"] is True  # from the supplied list
    assert vis["cta"] is True
    assert vis.get("trust_bar") is False  # chrome with no content -> hidden placeholder


def test_hero_and_faq_carry_editable_data() -> None:
    m = build_page_model(_DRAFT, design_profile=None, template="service", page_type="service", cta=_CTA)
    hero = next(s for s in m.sections if s.kind == "hero")
    assert hero.heading == "Automate the busywork"
    assert hero.data["subhead"]
    assert hero.data["buttons"][0]["label"] == "Book"
    faq = next(s for s in m.sections if s.kind == "faq")
    qs = [f["q"] for f in faq.data["faq"]]
    assert qs == ["How fast can we go live?", "Is our data safe?"]
    benefits = next(s for s in m.sections if s.kind == "benefits")
    titles = {c["title"] for c in benefits.data["cards"]}
    assert "Fast" in titles and "Agents" in titles


def test_model_round_trips_through_dict() -> None:
    m = build_page_model(_DRAFT, design_profile=None, template="service", page_type="service",
                         cta=_CTA, testimonials=["Nice. - X"])
    d = m.to_dict()
    again = page_model_from_dict(d)
    assert again.to_dict() == d  # byte-identical after a save/load cycle


def test_editor_edits_survive_and_render() -> None:
    m = build_page_model(_DRAFT, design_profile=None, template="service", page_type="service", cta=_CTA)
    d = m.to_dict()
    # Simulate an editor edit: change the hero heading + hide the benefits section.
    for s in d["sections"]:
        if s["kind"] == "hero":
            s["heading"] = "Edited headline"
        if s["kind"] == "benefits":
            s["visible"] = False
    edited = page_model_from_dict(d)
    html = model_to_html(edited, fragment=True)
    assert "Edited headline" in html
    assert "aios-benefits" not in html  # a hidden section is not rendered


def test_html_is_self_contained_and_styled() -> None:
    m = build_page_model(_DRAFT, design_profile=None, template="service", page_type="service",
                         cta=_CTA, testimonials=["Great. - X"])
    html = model_to_html(m, fragment=True)
    assert "<style>" in html and "aios-doc" in html
    assert "aios-hero" in html and "aios-faq" in html and "aios-cta" in html
    # No blank black-and-white text: real components (cards, accordion, buttons) present.
    assert 'class="card"' in html and "<details>" in html and 'class="btn' in html


def test_gbp_post_degrades_to_a_single_prose_section() -> None:
    m = build_page_model("# Update\n\nWe are open late this week.", design_profile=None,
                         template=None, page_type="gbp_post")
    assert len(m.sections) == 1 and m.sections[0].kind == "prose"
    assert "We are open late" in model_to_html(m, fragment=True)


def test_analyzed_dark_profile_styles_the_page() -> None:
    profile = {"palette": {"primary": "#f4f8ff", "background": "#0a0e1a", "text": "#c7d2e0",
                           "accent": "#22d3ee", "secondary": "#8a99b5"},
               "layout": {"blueprint": [{"kind": "hero", "layout": "centered"},
                                        {"kind": "cta", "layout": "banner"}]}}
    m = build_page_model(_DRAFT, design_profile=profile, template=None, page_type="service", cta=_CTA)
    html = model_to_html(m, fragment=True)
    assert "#0a0e1a" in html and "#22d3ee" in html  # the analyzed dark palette + cyan accent
