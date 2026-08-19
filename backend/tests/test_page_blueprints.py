"""Unit gate for the SHARED page-layout doctrine (``app.services.page_blueprints``):
the 7 named templates, the precedence-ordered blueprint resolver, the raw-section
coercion, and the two SYNC LOCKS that keep the doctrine single-sourced - the schema's
``PageTemplate`` literal must equal the module's template keys, and the committed skills
reference (``PAGE-TEMPLATES.md``) must equal the module's rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

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

_EXPECTED = {"service", "location", "service_area", "blog", "faq", "local", "homepage"}


def test_exactly_the_seven_named_templates() -> None:
    assert set(TEMPLATES) == _EXPECTED
    assert set(template_names()) == _EXPECTED
    assert len(template_names()) == 7


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
# The resolver precedence: template wins -> analyzed site -> default -> nothing.
# --------------------------------------------------------------------------- #
def test_explicit_template_wins_over_analyzed_profile() -> None:
    profile = {"layout": {"section_order": ["hero", "about", "cta"]}}
    specs = resolve_blueprint(design_profile=profile, template="faq", page_type="blog")
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["faq"].sections]


def test_analyzed_blueprint_used_when_no_template() -> None:
    profile = {
        "layout": {
            "blueprint": [
                {"kind": "hero", "layout": "split"},
                {"kind": "services", "layout": "grid"},
                {"kind": "cta", "layout": "banner"},
            ]
        }
    }
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="service")
    assert [s.kind for s in specs] == ["hero", "services", "cta"]
    assert specs[1].layout == "grid"


def test_analyzed_section_order_used_when_no_rich_blueprint() -> None:
    profile = {"layout": {"section_order": ["hero", "faq", "cta"]}}
    specs = resolve_blueprint(design_profile=profile, template=None, page_type="blog")
    assert [s.kind for s in specs] == ["hero", "faq", "cta"]


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
