"""The published body and the published stylesheet must describe the SAME page.

THE DEFECT THIS LOCKS OUT. A page's HTML and its CSS are produced by different functions
and sent in different fields of the publish payload, and they disagreed about which
renderer had run. A composed or hand-edited page's body came out of the model renderer in
the ``.aios-doc`` class vocabulary, while ``design_css`` carried rules written for the
flat-wrap renderer's ``.aios-page`` vocabulary. Every selector missed. The page published
with a complete structure and not one rule behind it - naked headings and paragraphs down
a white page, which is what a client sees and calls unacceptable, and which no test
noticed because both halves were individually correct.

The properties here are the ones that would let that happen again:

  * the body must carry no ``<style>`` block, because WordPress deletes one INCLUDING its
    contents - a stylesheet sent inside the body is a stylesheet thrown away;
  * the stylesheet must therefore be non-empty in the payload's own field;
  * and the two must share a class vocabulary, which is the only assertion that actually
    catches the drift - the other two passed throughout the outage.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

import pytest

from app.services.page_blueprints import resolve_blueprint
from app.services.page_compose import model_from_composed
from workers.tasks.content import _design_css_text, _shape_body_html

pytestmark = pytest.mark.unit


_DESIGN: dict[str, Any] = {
    "colors": {"primary": "#0b3d2e", "accent": "#c9a227", "background": "#ffffff",
               "text": "#12211c", "secondary": "#5a6b64"},
    "fonts": {"heading": "Fraunces, serif", "body": "Inter, sans-serif"},
    "radius": 14,
}


def _composed() -> list[dict[str, Any]]:
    """A filled service wireframe: the seven slots, with data in each."""
    return [
        {"kind": "hero", "heading": "Cold chain logistics for clinical trials",
         "data": {"subheading": "Validated shippers, monitored end to end.",
                  "bullets": [{"text": "Temperature excursion alerts"}]}},
        {"kind": "features", "heading": "What the service covers",
         "data": {"items": [{"title": "Validated packaging", "text": "Qualified to protocol."},
                            {"title": "Live monitoring", "text": "Every leg, every reading."}]}},
        {"kind": "process", "heading": "How a shipment runs",
         "data": {"steps": [{"title": "Scope the lane", "text": "Route, duration, risk."},
                            {"title": "Qualify the pack", "text": "Match to the protocol."}]}},
        {"kind": "faq", "heading": "Questions we get",
         "data": {"items": [{"question": "Do you handle customs?",
                             "answer": "Yes, on every cross-border lane."}]}},
        {"kind": "pricing", "heading": "Plans",
         "data": {"tiers": [{"name": "Lane", "price": "On request",
                             "summary": "One validated route."}]}},
        {"kind": "testimonials", "heading": "What sponsors say",
         "data": {"quotes": [{"quote": "Not one excursion in two years.",
                              "author": "R. Dalvi", "role": "Trial logistics lead"}]}},
        {"kind": "cta", "heading": "Talk to a lane planner",
         "data": {"text": "We will map the route before you commit.",
                  "button_label": "Request a lane review"}},
    ]


def _row(**over: Any) -> dict[str, Any]:
    specs = resolve_blueprint(design_profile=None, template="service", page_type="service")
    model = model_from_composed(
        _composed(), design=_DESIGN, title="Cold chain logistics", images=[],
        cta_url="https://example.com/contact",
    )
    row: dict[str, Any] = {
        "code": "CJ-1", "page_type": "service", "topic": "Cold chain logistics",
        "draft_md": "# Cold chain logistics\n\nProse mirror of the slots.",
        "source_pack": {"template": "service", "design_profile": _DESIGN,
                        "page_model": model.to_dict()},
    }
    assert specs, "the service template must resolve"
    row.update(over)
    return row


def _classes(html: str) -> set[str]:
    return {c for m in re.findall(r'class="([^"]+)"', html) for c in m.split()}


# --------------------------------------------------------------------------- #
def test_the_body_carries_no_stylesheet() -> None:
    """A ``<style>`` tag in the body is deleted with its contents before the post is
    saved, so sending one is not belt-and-braces - it is the stylesheet going missing."""
    body = _shape_body_html(_row(), "unused")
    assert "<style" not in body.lower()
    assert body.lstrip().startswith('<main class="aios-doc"')


def test_the_stylesheet_travels_in_its_own_field() -> None:
    css = _design_css_text(_row())
    assert css, "a composed page publishes with a stylesheet"
    assert "<style" not in css, "the plugin owns the wrapping tag"
    assert "aios-doc" in css


def test_the_body_and_the_stylesheet_share_a_class_vocabulary() -> None:
    """THE ASSERTION THAT WOULD HAVE CAUGHT IT.

    Both halves were individually well-formed while the page published unstyled; what was
    wrong was only that they were written about different pages. Every structural class the
    body uses must be addressed by at least one rule in the stylesheet that ships with it.
    """
    row = _row()
    body_classes = _classes(_shape_body_html(row, "unused"))
    css = _design_css_text(row)
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))

    structural = {c for c in body_classes if not c.startswith("aios-")}
    unstyled = sorted(c for c in structural if c not in styled)
    assert not unstyled, f"the body uses classes the shipped stylesheet never mentions: {unstyled}"


def test_every_composed_section_reaches_the_published_body() -> None:
    """Seven slots in, seven sections out. The failure being locked out is the quiet one:
    a renderer that knows five of the kinds drops the other two and publishes a page that
    looks finished and is missing its price list and its proof."""
    body = _shape_body_html(_row(), "unused")
    for kind in ("hero", "features", "process", "faq", "pricing", "testimonials", "cta"):
        assert f"aios-{kind}" in body, f"the {kind} slot never reached the page"
    # And the DATA inside them, not merely the wrapper.
    assert "Validated packaging" in body      # a feature card
    assert "Scope the lane" in body           # a process step's own title
    assert "Do you handle customs?" in body   # an FAQ question
    assert "On request" in body               # a price
    assert "R. Dalvi" in body                 # a testimonial's attribution


def test_a_prose_page_is_unchanged() -> None:
    """No model -> the flat-wrap renderer and its own stylesheet, exactly as before."""
    row = _row()
    row["source_pack"] = {"template": "blog"}
    row["page_type"] = "blog"
    body = _shape_body_html(row, "# Title\n\nA paragraph.")
    assert "aios-doc" not in body
    assert "<style" not in body


# --------------------------------------------------------------------------- #
# ONE RENDERER PER PAGE.
#
# MEASURED ON A LIVE PUSH (spotino.org post 284). The payload carried BOTH our styled
# HTML body and an Elementor widget tree. Elementor renders its tree INSTEAD of
# `post_content`, so the body was discarded - and with it every `design_css` rule, all of
# which are scoped `.aios-doc …` and match nothing in Elementor's markup. The head carried
# 8.9 KB of the client's design system and the page rendered in the THEME's typeface and
# spacing. The operator's report was exactly right: "both same pages, but different
# layout".
# --------------------------------------------------------------------------- #
class TestAComposedPageShipsOneRenderer:
    @staticmethod
    def _payload(**over: Any) -> dict[str, Any]:
        from app.config import Settings
        from workers.tasks.content import _plugin_payload

        row = _row(**over)
        settings = Settings(
            _env_file=None, app_env="dev", content_elementor_enabled=True,
            vault_master_key="0" * 64,
        )
        return _plugin_payload(row, str(row["draft_md"]), "A page", settings=settings)

    def test_no_elementor_tree_rides_along(self) -> None:
        """Sending one is not belt-and-braces: it is the styled body being thrown away."""
        assert "elementor_data" not in self._payload()

    def test_the_body_that_ships_is_the_styled_one(self) -> None:
        payload = self._payload()
        assert str(payload["content"]).lstrip().startswith('<main class="aios-doc"')
        assert payload["design_css"], "and it ships with the stylesheet that matches it"

    def test_a_prose_page_still_gets_its_elementor_tree(self) -> None:
        """The rule is about a CONFLICT, not about Elementor. A page with no composed
        model publishes a flat render that the widget tree genuinely improves on."""
        payload = self._payload(source_pack={"template": "blog"}, page_type="blog")
        assert "elementor_data" in payload


class TestTheDesignTravelsWithTheTypefaces:
    """Naming a family is not having it. `font-family: Poppins, ...` on a site that never
    loaded Poppins renders in whatever comes next - normally the theme's font - while the
    CSS is exactly right and nothing reports a problem."""

    def test_the_families_ship_beside_the_css(self) -> None:
        from app.config import Settings
        from workers.tasks.content import _plugin_payload

        row = _row()
        row["source_pack"]["design_profile"] = {
            **_DESIGN,
            "typography": {"heading_font": "Poppins, sans-serif",
                           "body_font": "Poppins, sans-serif"},
        }
        row["source_pack"]["page_model"]["design"] = row["source_pack"]["design_profile"]
        payload = _plugin_payload(
            row, str(row["draft_md"]), "A page",
            settings=Settings(_env_file=None, app_env="dev", vault_master_key="0" * 64),
        )
        assert payload["design_fonts"] == ["Poppins"]
        assert "Poppins" in payload["design_css"]

    def test_system_and_generic_families_are_not_requested(self) -> None:
        """Asking a font host for "sans-serif" is a 404 the page waits on."""
        from app.services.page_model import font_families

        assert font_families(
            {"typography": {"heading_font": "Georgia, serif", "body_font": "Arial, sans-serif"}}
        ) == []

    def test_the_analyzed_order_is_preserved(self) -> None:
        from app.services.page_model import font_families

        assert font_families({
            "typography": {"heading_font": '"Fraunces", Georgia, serif',
                           "body_font": "Inter, system-ui, sans-serif"},
        }) == ["Fraunces", "Inter"]


class TestTheSiteIsToldNotToDecorateAFinishedPage:
    """A composed page arrives complete - hero, sections, FAQ accordion, closing CTA.

    The publisher plugin's article renderer adds a byline, a generated table of contents,
    a key-takeaways box, an FAQ accordion and a call-to-action banner, because that is
    what a long-form ARTICLE's flat body needs. Applied to a finished page it produces
    each of those TWICE, which is the reported difference between the local preview and
    the published page. The flag is how the site knows which kind it has.
    """

    @staticmethod
    def _payload(**over: Any) -> dict[str, Any]:
        from app.config import Settings
        from workers.tasks.content import _plugin_payload

        row = _row(**over)
        return _plugin_payload(
            row, str(row["draft_md"]), "A page",
            settings=Settings(_env_file=None, app_env="dev", vault_master_key="0" * 64),
        )

    def test_a_composed_page_is_flagged_self_contained(self) -> None:
        assert self._payload()["self_contained"] is True

    def test_and_ships_none_of_the_components_it_already_has(self) -> None:
        payload = self._payload()
        for field in ("faq", "cta", "key_takeaways"):
            assert field not in payload, f"{field} would render a second time on the page"

    def test_a_prose_article_still_gets_them(self) -> None:
        """The components are not a mistake - they are what an article's flat body needs.
        Only a page that already carries its own must not be given a second set."""
        payload = self._payload(source_pack={"template": "blog"}, page_type="blog")
        assert "self_contained" not in payload
        assert "cta" in payload


class TestARePushUpdatesThePageRatherThanAddingAnother:
    """Every push used to create a new post, so re-pushing a page after a fix left the
    previous attempt behind. Two pushes of two pages put four drafts on the client's site
    and the operator had to work out which was current."""

    @staticmethod
    def _payload(**over: Any) -> dict[str, Any]:
        from app.config import Settings
        from workers.tasks.content import _plugin_payload

        row = _row(**over)
        return _plugin_payload(
            row, str(row["draft_md"]), "A page",
            settings=Settings(_env_file=None, app_env="dev", vault_master_key="0" * 64),
        )

    def test_a_page_that_has_a_post_names_it(self) -> None:
        assert self._payload(wp_post_id="288")["post_id"] == 288

    def test_a_first_push_names_nothing(self) -> None:
        assert "post_id" not in self._payload()

    def test_a_junk_post_id_is_not_forwarded(self) -> None:
        """The column is text and has held non-numeric values. Forwarding one would make
        the site's guard the only thing between us and a bad request."""
        for junk in ("", "  ", "abc", "12a", "-4"):
            assert "post_id" not in self._payload(wp_post_id=junk), junk


class TestAnUnfetchableFamilyIsNotRequested:
    """A Google Fonts css2 request containing ANY unknown family answers 400 and returns
    no CSS at all - so one bad name takes every good one in the same URL down with it and
    the page silently renders in the theme's font.

    Two defences, and both are needed. The plugin asks for one family per stylesheet so a
    bad name fails alone; and a name that is obviously a BUILD ARTEFACT is never asked for
    in the first place. `Inter Fallback` was measured on a live capture - it is a
    metric-matched face Next.js generates into that one site's build, so the analyzer is
    right to transcribe it and wrong to send anyone looking for it.
    """

    def test_a_next_js_metric_fallback_is_dropped(self) -> None:
        from app.services.page_model import font_families

        assert font_families(
            {"typography": {"heading_font": 'Inter, "Inter Fallback"',
                            "body_font": 'Inter, "Inter Fallback"'}}
        ) == ["Inter"]

    def test_a_real_two_word_family_survives(self) -> None:
        """The rule keys on the artefact SUFFIX, not on the space: plenty of real
        typefaces are two words and dropping them would be worse than the bug."""
        from app.services.page_model import font_families

        assert font_families(
            {"typography": {"heading_font": '"Playfair Display", serif',
                            "body_font": '"Source Sans 3", sans-serif'}}
        ) == ["Playfair Display", "Source Sans 3"]


class TestASectionWithNothingToDrawIsNotPublished:
    """MEASURED ON EVERY CHROME KIND. `contact`, `related`, `map`, `hours`, `gallery`,
    `trust_bar` and `search` were kept in the model with an empty payload, on the
    reasoning that the theme fills them from live data. That is true of a page whose flat
    body the publisher plugin decorates, and false of a composed page - which publishes as
    one self-contained document nothing else writes into. Every one of them rendered as a
    section heading with blank space under it.

    It reached two shipped templates: `location` carries `contact`, `faq` carries
    `related`, and both are evidence-gated - so when they appear the data is guaranteed to
    exist. They were the slots most certain to render empty for exactly the reason they
    were most worth rendering.
    """

    _SLOTS: ClassVar[list[dict[str, Any]]] = [
        {"kind": "hero", "heading": "H", "data": {"subheading": "S"}},
        {"kind": "contact", "heading": "Find us", "data": {}},
        {"kind": "related", "heading": "More pages", "data": {}},
        {"kind": "map", "heading": "Map", "data": {}},
        {"kind": "cta", "heading": "C", "data": {"text": "T"}},
    ]

    def test_with_no_data_the_empty_bands_are_dropped(self) -> None:
        from app.services.page_compose import model_from_composed

        model = model_from_composed(self._SLOTS, design={}, title="t", images=[])
        assert [s.kind for s in model.sections] == ["hero", "cta"]

    def test_with_real_data_they_render_their_data(self) -> None:
        from app.services.page_compose import model_from_composed
        from app.services.page_model import model_body_html

        model = model_from_composed(
            self._SLOTS, design={}, title="t", images=[],
            nap={"business_name": "SPOTiNO", "address": "12 Gulberg, Lahore",
                 "phone": "+92 300 1234567"},
            internal_links={"football coaching lahore": "https://spotino.org/coaching"},
        )
        assert [s.kind for s in model.sections] == ["hero", "contact", "related", "cta"]
        html = model_body_html(model)
        assert "12 Gulberg, Lahore" in html and "+92 300 1234567" in html
        assert "https://spotino.org/coaching" in html
        assert "aios-map" not in html, "a map has no data to draw and must still drop"

    def test_a_partial_nap_prints_only_what_the_client_gave(self) -> None:
        """A contact block with an empty "Phone:" label is worse than one that does not
        mention a phone - it reads as a page that lost its data."""
        from app.services.page_compose import model_from_composed
        from app.services.page_model import model_body_html

        model = model_from_composed(
            self._SLOTS, design={}, title="t", images=[],
            nap={"business_name": "SPOTiNO", "phone": "+92 300 1234567"},
        )
        html = model_body_html(model)
        assert "Phone" in html
        assert "Address" not in html and "Hours" not in html


class TestTheThemeCannotTakeTheTypefaceBack:
    """MEASURED ON A LIVE SITE. The page published carrying the client's whole design
    system and rendered in the THEME's typeface.

    `.aios-doc {font-family}` sets the family once and lets it inherit, which is correct
    CSS and not enough on somebody else's WordPress: inheritance loses to ANY rule that
    matches the element, so a theme styling `h2` or `.entry-content p` directly wins. The
    family is therefore restated on the elements themselves.
    """

    @staticmethod
    def _css() -> str:
        from app.services.page_model import PageModel, model_css

        return model_css(PageModel(design={
            "typography": {"heading_font": "Poppins, sans-serif",
                           "body_font": "Poppins, sans-serif"},
        }))

    def test_headings_name_the_family_directly(self) -> None:
        css = self._css()
        for sel in (".aios-doc h1", ".aios-doc h4"):
            assert sel in css, f"{sel} must carry the heading family itself"

    def test_body_elements_name_the_family_directly(self) -> None:
        css = self._css()
        for sel in (".aios-doc p", ".aios-doc li", ".aios-doc a", ".aios-doc blockquote"):
            assert sel in css, f"{sel} must carry the body family itself"

    def test_no_important_is_used(self) -> None:
        """A theme's own `!important` must still win. Overriding an author's explicit
        declaration would make OUR page the one nobody can restyle - which is the same
        disease in the other direction."""
        assert "!important" not in self._css()
