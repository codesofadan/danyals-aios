"""Unit gate for the Elementor-editable page output (``app.services.elementor`` +
the worker's plugin-payload wiring).

Proves the PURE builder turns a reviewed Markdown draft into a VALID Elementor widget
tree - top-level sections, each with columns -> widgets, unique deterministic ids, and
heading / text-editor / image / button widgets for the corresponding Markdown - that a
``design_profile`` injects the ordered section names + palette colours, and that
empty / plain input degrades to a single text section. Also proves the plugin publish
payload carries ``elementor_data`` when the setting is enabled and is byte-identical
(no extra keys) when it is disabled. No Celery, no DB, no network.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.config import Settings
from app.services.elementor import build_elementor_data, elementor_json

pytestmark = pytest.mark.unit


_DRAFT = (
    "# The Ultimate Guide\n\n"
    "An intro paragraph with a [link](https://example.test) and **bold**.\n\n"
    "![a hero photo](https://cdn.test/hero.png)\n\n"
    "## Why it matters\n\n"
    "Some body copy explaining the value.\n\n"
    "- First point\n"
    "- Second point\n\n"
    "## Get started\n\n"
    "A closing paragraph.\n\n"
    "[Book a call](https://example.test/contact)\n"
)


# --------------------------------------------------------------------------- #
# Tree-shape invariants (walk the whole tree and assert the Elementor contract).
# --------------------------------------------------------------------------- #
def _walk_widgets(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    widgets: list[dict[str, Any]] = []
    for section in tree:
        for column in section["elements"]:
            widgets.extend(column["elements"])
    return widgets


def _collect_ids(tree: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for section in tree:
        ids.append(section["id"])
        for column in section["elements"]:
            ids.append(column["id"])
            ids.extend(w["id"] for w in column["elements"])
    return ids


def test_builder_emits_a_valid_elementor_tree() -> None:
    tree = build_elementor_data(_DRAFT)

    assert isinstance(tree, list) and tree, "top level is a non-empty list of sections"
    # Structural contract: section -> column(s) -> widget(s).
    for section in tree:
        assert section["elType"] == "section"
        assert isinstance(section["settings"], dict)
        assert section["elements"], "a section has at least one column"
        for column in section["elements"]:
            assert column["elType"] == "column"
            assert column["settings"]["_column_size"] == 100
            assert column["elements"], "a column has at least one widget"
            for widget in column["elements"]:
                assert widget["elType"] == "widget"
                assert widget["widgetType"] in {"heading", "text-editor", "image", "button"}

    widgets = _walk_widgets(tree)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for w in widgets:
        by_type.setdefault(w["widgetType"], []).append(w)

    # Every Markdown block kind mapped to its widget.
    headings = by_type["heading"]
    assert any(h["settings"] == {"title": "The Ultimate Guide", "header_size": "h1"} for h in headings)
    assert any(h["settings"]["header_size"] == "h2" for h in headings)
    # A paragraph -> text-editor with inline HTML (link + bold preserved).
    editors = [w["settings"]["editor"] for w in by_type["text-editor"]]
    assert any('<a href="https://example.test">link</a>' in e and "<strong>bold</strong>" in e for e in editors)
    # A bullet run -> ONE text-editor <ul> widget.
    assert any(e == "<ul><li>First point</li><li>Second point</li></ul>" for e in editors)
    # An image line -> image widget with the url.
    assert by_type["image"][0]["settings"]["image"]["url"] == "https://cdn.test/hero.png"
    # A standalone link line -> a button (CTA) with text + link.
    button = by_type["button"][0]
    assert button["settings"]["text"] == "Book a call"
    assert button["settings"]["link"] == {"url": "https://example.test/contact"}


def test_ids_are_unique_and_deterministic() -> None:
    ids = _collect_ids(build_elementor_data(_DRAFT))
    assert len(ids) == len(set(ids)), "every element id is unique"
    assert all(len(i) == 8 and all(c in "0123456789abcdef" for c in i) for i in ids), "ids are 8-hex"
    # Deterministic: same draft -> byte-identical tree (no clock / randomness).
    assert build_elementor_data(_DRAFT) == build_elementor_data(_DRAFT)


def test_headings_split_content_into_multiple_sections() -> None:
    # The draft has an intro + two H2 sections -> at least three top-level sections.
    tree = build_elementor_data(_DRAFT)
    assert len(tree) >= 3


# --------------------------------------------------------------------------- #
# Design profile: named sections + palette injection.
# --------------------------------------------------------------------------- #
def test_design_profile_injects_section_names_and_palette() -> None:
    profile = {
        "palette": {
            "primary": "#0a0a0a",
            "secondary": "#333333",
            "background": "#fffbea",
            "text": "#111111",
            "accent": "#ff5500",
        },
        "layout": {"section_order": ["hero", "services", "cta"]},
    }
    tree = build_elementor_data(_DRAFT, design_profile=profile)
    raw = elementor_json(_DRAFT, profile)

    # Section names land as aios-<slug> CSS classes on the sections.
    classes = [s["settings"].get("_css_classes") for s in tree]
    assert "aios-hero" in classes
    assert any(c in classes for c in ("aios-services", "aios-cta"))

    # Palette carried into section background + widget colours.
    assert any(s["settings"].get("background_color") == "#fffbea" for s in tree)
    widgets = _walk_widgets(tree)
    assert any(w.get("settings", {}).get("title_color") == "#0a0a0a" for w in widgets if w["widgetType"] == "heading")
    assert any(w.get("settings", {}).get("text_color") == "#111111" for w in widgets if w["widgetType"] == "text-editor")
    btn = next(w for w in widgets if w["widgetType"] == "button")
    assert btn["settings"]["button_background_color"] == "#ff5500"
    assert btn["settings"]["button_text_color"] == "#fffbea"

    # elementor_json is compact (no spaces after separators) valid JSON of the tree.
    assert ", " not in raw and '": ' not in raw
    assert json.loads(raw) == tree


def test_design_profile_applies_typography_components_and_container() -> None:
    # The FULL profile (beyond palette + order): typography, components, container width,
    # and hero styling must land on the widget / section settings.
    profile = {
        "palette": {
            "primary": "#0a0a0a", "secondary": "#333333", "background": "#ffffff",
            "text": "#111111", "accent": "#ff5500",
        },
        "typography": {
            "heading_font": "Poppins, sans-serif", "body_font": "Inter, sans-serif",
            "base_size": "18px",
        },
        "layout": {
            "container_width": "1080px", "section_order": ["hero", "services", "cta"],
            "hero_style": "centered",
        },
        "components": {
            "button_style": "solid pill", "card_style": "soft shadow", "spacing_scale": "spacious",
        },
    }
    tree = build_elementor_data(_DRAFT, design_profile=profile)
    widgets = _walk_widgets(tree)

    # Typography: heading font on heading widgets; body font + base size on text widgets.
    heads = [w["settings"] for w in widgets if w["widgetType"] == "heading"]
    assert any(s.get("title_typography_typography") == "custom" for s in heads)
    assert any(s.get("title_typography_font_family") == "Poppins, sans-serif" for s in heads)
    texts = [w["settings"] for w in widgets if w["widgetType"] == "text-editor"]
    assert any(s.get("typography_font_family") == "Inter, sans-serif" for s in texts)
    assert any(s.get("typography_font_size") == {"unit": "px", "size": 18} for s in texts)

    # Components: the CTA button gets a pill radius (999px) from button_style.
    btn = next(w["settings"] for w in widgets if w["widgetType"] == "button")
    assert btn["border_radius"]["top"] == 999

    # Layout: the container width lands on every section; the hero (first) centres + pads.
    assert any(s["settings"].get("content_width") == {"unit": "px", "size": 1080} for s in tree)
    assert tree[0]["settings"].get("content_position") == "center"
    # spacing_scale (spacious -> 72px) drives a NON-hero section's vertical padding.
    assert any(s["settings"].get("padding", {}).get("top") == "72" for s in tree[1:])
    # elementor_json round-trips the tree (the nested typography / padding dicts included).
    assert json.loads(elementor_json(_DRAFT, profile)) == tree


def test_empty_and_plain_input_degrade_to_a_single_text_section() -> None:
    for draft in ("", "   \n\n   "):
        tree = build_elementor_data(draft)
        assert len(tree) == 1
        widgets = _walk_widgets(tree)
        assert len(widgets) == 1 and widgets[0]["widgetType"] == "text-editor"

    # Plain prose with no headings -> ONE section holding the paragraph text widget.
    plain = build_elementor_data("Just one paragraph, no headings at all.")
    assert len(plain) == 1
    pw = _walk_widgets(plain)
    assert len(pw) == 1 and pw[0]["widgetType"] == "text-editor"
    assert "Just one paragraph" in pw[0]["settings"]["editor"]


# --------------------------------------------------------------------------- #
# Worker plugin-payload wiring: carried when enabled, byte-identical when disabled.
# --------------------------------------------------------------------------- #
def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _row() -> dict[str, Any]:
    return {
        "code": "CJ-9001",
        "topic": "the ultimate guide",
        "outline": {"meta": {"title": "The Ultimate Guide (2026)", "description": "A definitive guide."}},
        "keyword_map": {"primary": "ultimate guide"},
        "source_pack": {
            "wp_site_url": "https://client.test",
            "design_profile": {"layout": {"section_order": ["hero", "cta"]}},
        },
    }


def test_plugin_payload_carries_elementor_when_enabled() -> None:
    from workers.tasks.content import _plugin_payload

    payload = _plugin_payload(_row(), _DRAFT, "The Ultimate Guide", settings=_settings(content_elementor_enabled=True))
    assert payload["elementor_edit_mode"] == "builder"
    tree = json.loads(payload["elementor_data"])
    assert isinstance(tree, list) and tree
    # The design profile in source_pack drove the named sections; the rich composer now
    # carries the per-kind layout variant too (aios-hero aios-layout-<variant>).
    assert any(
        str(s["settings"].get("_css_classes", "")).startswith("aios-hero") for s in tree
    )
    # The flat HTML body is STILL present (the non-Elementor fallback), and it
    # carries a real top-level heading. Matched as an H1 ELEMENT rather than the
    # literal "<h1>": the Gutenberg emitter attributes its headings
    # (`<h1 class="wp-block-heading">`), so a bare-tag substring check asserted a
    # formatting detail, not the SEO property that actually matters.
    body = payload["content"]
    assert body
    assert re.search(r"<h1\b[^>]*>", body), "publish body must contain an <h1> element"


def test_plugin_payload_carries_design_css_for_default_theme() -> None:
    # The analyzed design must also reach a NON-Elementor (plain default theme) site: the
    # payload carries a separate ``design_css`` field the plugin enqueues in <head>. It is
    # scoped to .aios-page, carries the analyzed palette, and rides regardless of the
    # Elementor flag (it styles the flat-HTML fallback body).
    from workers.tasks.content import _plugin_payload

    row = _row()
    row["source_pack"]["design_profile"] = {
        "palette": {"primary": "#0a0a0a", "background": "#fffbea", "text": "#111", "accent": "#ff5500"},
        "typography": {"heading_font": "Poppins, sans-serif", "body_font": "Inter, sans-serif"},
        "layout": {"container_width": "1080px", "section_order": ["hero", "cta"], "hero_style": "centered"},
        "components": {"button_style": "solid pill", "card_style": "soft shadow", "spacing_scale": "spacious"},
    }
    for flag in (True, False):
        payload = _plugin_payload(row, _DRAFT, "The Ultimate Guide", settings=_settings(content_elementor_enabled=flag))
        css = payload["design_css"]
        assert ".aios-page" in css              # scoped to the generated body wrapper
        assert "#ff5500" in css                 # the analyzed accent colour is applied
        assert "Poppins, sans-serif" in css     # the analyzed heading font is applied
        assert "<style>" not in css             # raw CSS only; the plugin owns the wrapper
        # The flat body itself still carries NO inline <style> (wp_kses_post would dump it).
        assert "<style>" not in payload["content"]
        # A page built to match an analyzed site is a full-width landing page.
        assert payload["full_width"] is True


def test_plugin_payload_full_width_by_page_type_without_profile() -> None:
    # No design profile, but a landing page_type (service) -> full width. A blog stays
    # narrow (no full_width key), so long-form articles keep the reading measure.
    from workers.tasks.content import _plugin_payload

    def _bare(page_type: str) -> dict[str, Any]:
        return {
            "code": "CJ-9002", "topic": "t", "page_type": page_type,
            "outline": {"meta": {"title": "T", "description": "d"}},
            "keyword_map": {"primary": "t"},
            "source_pack": {"wp_site_url": "https://client.test"},
        }

    service = _plugin_payload(_bare("service"), _DRAFT, "T", settings=_settings())
    blog = _plugin_payload(_bare("blog"), _DRAFT, "T", settings=_settings())
    assert service.get("full_width") is True
    assert "full_width" not in blog


def test_plugin_payload_is_byte_identical_when_disabled() -> None:
    from workers.tasks.content import _plugin_payload

    off = _settings(content_elementor_enabled=False)
    on = _settings(content_elementor_enabled=True)
    disabled = _plugin_payload(_row(), _DRAFT, "The Ultimate Guide", settings=off)
    enabled = _plugin_payload(_row(), _DRAFT, "The Ultimate Guide", settings=on)

    assert "elementor_data" not in disabled
    assert "elementor_edit_mode" not in disabled
    # Disabling adds NO keys beyond the pre-Elementor payload; the only delta enabling
    # introduces is exactly the two elementor_* keys.
    assert set(enabled) - set(disabled) == {"elementor_data", "elementor_edit_mode"}
    assert {k: disabled[k] for k in disabled} == {k: enabled[k] for k in disabled}


# --------------------------------------------------------------------------- #
# QA 23: generated pages render narrow instead of full width
# --------------------------------------------------------------------------- #
# Three independent causes, each pinned below. The plan that preceded this work
# asserted "content_width is already emitted on virtually every page, so only
# stretch_section is missing" - measurement proved that FALSE, and acting on it
# would have stretched uncapped sections and run the text off the left viewport.


def test_every_section_carries_a_content_width_even_with_no_tokens() -> None:
    """The cap is unconditional. It used to be double-gated and often absent.

    Two real holes it closes: `build_elementor_data`'s simple path passes tokens=None
    outright, and `_design_tokens` returns `tokens or None` - so a profile with a font
    but no `layout.container_width` yields a TRUTHY dict with no container_px, which
    defeats the `or dict(_CLASSIC_TOKENS)` fallback its callers rely on.
    """
    from app.services.elementor import build_elementor_data

    # (a) no profile at all -> the simple path, tokens=None
    for section in build_elementor_data(_DRAFT, design_profile=None):
        assert section["settings"]["content_width"]["size"] > 0

    # (b) a profile carrying a font but NO container width - the truthy-dict hole
    thin = {"typography": {"body_font": "Inter"}}
    for section in build_elementor_data(_DRAFT, design_profile=thin):
        assert section["settings"]["content_width"]["size"] > 0


def test_a_full_width_page_is_a_stretched_band_with_boxed_content() -> None:
    """Stretch breaks out of the theme's box; `boxed` keeps the text on the measure.

    Never `layout: "full_width"` - the replica emitter recorded on a real client site
    that pairing it with stretch ran the text edge-to-edge and off the left viewport.
    """
    import json as _json

    from app.services.elementor import elementor_json

    tree = _json.loads(elementor_json(_DRAFT, None, full_width=True))
    assert tree, "a full-width page must still produce sections"
    for section in tree:
        st = section["settings"]
        assert st["stretch_section"] == "section-stretched"
        assert st["layout"] == "boxed"
        assert st["content_width"]["size"] > 0  # stretched but never uncapped


def test_an_article_is_not_stretched() -> None:
    """A blog post keeps the reading measure - full width is for landing pages."""
    import json as _json

    from app.services.elementor import elementor_json

    for section in _json.loads(elementor_json(_DRAFT, None)):
        assert "stretch_section" not in section["settings"]


def test_a_landing_page_is_published_as_a_page_not_a_blog_post() -> None:
    """The cause QA actually described: "content is centered in a narrow/tab-like
    layout with very large margins".

    A service page published as a `post` gets the theme's SINGLE-POST template - a
    narrow blog column. Nothing to do with Elementor. The replica path already learned
    this and says so in the same words (test_replica_publish.py: "a POST renders in
    the theme's narrow blog column"). Articles stay posts so blog permalinks,
    categories and the feed are untouched.
    """
    from workers.tasks.content import _plugin_payload

    def _bare(page_type: str) -> dict[str, Any]:
        return {
            "code": "CJ-9003", "topic": "t", "page_type": page_type,
            "outline": {"meta": {"title": "T", "description": "d"}},
            "keyword_map": {"primary": "t"},
            "source_pack": {"wp_site_url": "https://client.test"},
        }

    assert _plugin_payload(_bare("service"), _DRAFT, "T", settings=_settings())["post_type"] == "page"
    assert _plugin_payload(_bare("local"), _DRAFT, "T", settings=_settings())["post_type"] == "page"
    assert _plugin_payload(_bare("blog"), _DRAFT, "T", settings=_settings())["post_type"] == "post"


def test_the_published_payload_stretches_exactly_when_it_claims_full_width() -> None:
    """One predicate drives the post type, the plugin flag AND the Elementor stretch,
    so they can no longer disagree about what kind of page this is."""
    import json as _json

    from workers.tasks.content import _plugin_payload

    def _bare(page_type: str) -> dict[str, Any]:
        return {
            "code": "CJ-9004", "topic": "t", "page_type": page_type,
            "outline": {"meta": {"title": "T", "description": "d"}},
            "keyword_map": {"primary": "t"},
            "source_pack": {"wp_site_url": "https://client.test"},
        }

    service = _plugin_payload(_bare("service"), _DRAFT, "T", settings=_settings())
    assert service.get("full_width") is True
    assert service["post_type"] == "page"
    for section in _json.loads(service["elementor_data"]):
        assert section["settings"]["stretch_section"] == "section-stretched"

    blog = _plugin_payload(_bare("blog"), _DRAFT, "T", settings=_settings())
    assert "full_width" not in blog
    assert blog["post_type"] == "post"
    for section in _json.loads(blog["elementor_data"]):
        assert "stretch_section" not in section["settings"]


def test_the_content_tree_passes_the_elementor_oracle() -> None:
    """The content emitter has never been validated against Elementor's registry.

    `validate_tree` runs at exactly ONE production site - the replica path - so any
    key the content emitter invents reaches WordPress unchecked and is "stored and
    silently ignored", which is the failure mode that function's docstring says
    already shipped two real bugs. This certifies the three width keys are real
    Elementor 4.7 controls, and guards every future addition here.
    """
    import json as _json

    from app.services.elementor import elementor_json
    from app.services.elementor_replica import validate_tree

    validate_tree(_json.loads(elementor_json(_DRAFT, None, full_width=True)))
    validate_tree(_json.loads(elementor_json(_DRAFT, None)))
