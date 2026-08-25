"""P6.6: point at a URL, get back an editable Elementor page.

Every behaviour pinned here was found by running the converter against a REAL page
(https://spotino.org/hy/, 416KB, Elementor-built) rather than against a fixture written
to pass. The fixtures below reproduce what that page actually does.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.html_capture import capture_html
from app.services.html_to_elementor import (
    PLACEHOLDER_MARKER,
    build_document,
    meta_payload,
    style_from,
)

pytestmark = pytest.mark.unit

# The shape a real Elementor page has: theme chrome OUTSIDE the content root, and the
# page's own header built as widgets INSIDE it.
_PAGE = """<!doctype html><html lang="en"><head>
<title>hy - SPOTiNO</title>
<meta name="description" content="Handmade sofas built to order." />
<meta property="og:image" content="/img/og.jpg" />
<link rel="canonical" href="https://spotino.org/hy/" />
<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto:400|Raleway:700" />
<style>.x{color:red}</style>
</head><body>
<div class="theme-header"><a href="#main" class="screen-reader">Skip to main content</a>
  <div class="logo">AM SOFA STUDIO</div><ul><li>Collections</li><li>Contact</li></ul></div>
<main>
<div data-elementor-type="wp-page" data-elementor-id="99" class="elementor">
  <section>
    <h1 style="color:#111">Comfort that feels like home</h1>
    <p>Custom sofas built to your measurements.</p>
    <a href="/collection" class="elementor-button">Explore the collection</a>
  </section>
  <section>
    <h2>Our premium collection</h2>
    <img src="data:image/svg+xml,PLACEHOLDER" data-src="/img/sofa.jpg" alt="Velvet sofa" />
    <ul><li>Kiln-dried frame</li><li>Ten-year warranty</li></ul>
    <hr />
    <script>var tracking = 1;</script>
  </section>
</div>
</main>
<footer><p>© 2026 SPOTiNO</p></footer>
</body></html>"""


def _page(html: str = _PAGE) -> Any:
    return capture_html(html, base_url="https://spotino.org/hy/")


class TestTheContentBoundary:
    """MEASURED on the real page: the site's logo and nav are plain <div>s, not
    <header>/<nav>. Skipping by tag alone captured "Skip to main content", the logo
    letters and the theme's page-title <h1> as page content - the rebuild would have
    opened with the client's own chrome duplicated inside the body."""

    def test_theme_chrome_outside_the_root_is_not_captured(self) -> None:
        text = " ".join(b.text for b in _page().blocks)
        assert "AM SOFA STUDIO" not in text
        assert "Collections" not in text
        assert "2026 SPOTiNO" not in text, "the footer is the theme's, not the page's"

    def test_content_inside_the_root_is_captured(self) -> None:
        text = " ".join(b.text for b in _page().blocks)
        assert "Comfort that feels like home" in text
        assert "Custom sofas built to your measurements." in text

    def test_a_skip_link_is_dropped_by_its_text(self) -> None:
        """Its CLASS rarely says "skip"; its TEXT always does. Reproducing it puts a
        stray "Skip to main content" button at the top of the rebuilt page."""
        assert not any("Skip to main" in b.text for b in _page().blocks)

    def test_scripts_and_styles_never_become_content(self) -> None:
        text = " ".join(b.text for b in _page().blocks)
        assert "tracking" not in text and "color:red" not in text

    def test_a_page_with_no_elementor_root_falls_back_to_main(self) -> None:
        html = "<html><body><div>chrome</div><main><h1>Real</h1></main></body></html>"
        blocks = capture_html(html).blocks
        assert [b.text for b in blocks] == ["Real"]


class TestLazyLoadedImages:
    """An Elementor page ships `src="data:image/svg+xml,..."` with the real file in
    `data-src`. Taking `src` naively reproduces the page with every image replaced by a
    grey rectangle."""

    def test_the_real_file_is_taken_over_the_placeholder_src(self) -> None:
        img = next(b for b in _page().blocks if b.kind == "image")
        assert img.url == "https://spotino.org/img/sofa.jpg"
        assert img.alt == "Velvet sofa"

    def test_a_data_uri_with_no_real_source_is_not_an_image(self) -> None:
        html = '<main><img src="data:image/png;base64,AAA" alt="x" /></main>'
        assert not [b for b in capture_html(html).blocks if b.kind == "image"]

    def test_the_widest_srcset_candidate_wins(self) -> None:
        html = ('<main><img srcset="/s.jpg 400w, /l.jpg 1600w, /m.jpg 800w" '
                'src="data:image/gif;base64,R0" alt="a" /></main>')
        img = next(b for b in capture_html(html, base_url="https://x.test/").blocks
                   if b.kind == "image")
        assert img.url == "https://x.test/l.jpg"

    def test_relative_urls_become_absolute(self) -> None:
        img = next(b for b in _page().blocks if b.kind == "image")
        assert img.url.startswith("https://spotino.org/")


class TestWhatBecomesWhichWidget:
    def _widgets(self, page: Any = None) -> dict[str, int]:
        tree, _notes = build_document(page or _page())
        out: dict[str, int] = {}

        def walk(nodes: list[dict[str, Any]]) -> None:
            for n in nodes:
                if n.get("widgetType"):
                    out[n["widgetType"]] = out.get(n["widgetType"], 0) + 1
                walk(n.get("elements") or [])

        walk(tree)
        return out

    def test_every_emitted_widget_is_elementor_free_core(self) -> None:
        """Nothing custom, nothing Pro, no registration step - which is the entire
        reason for doing this rather than shipping a block of HTML."""
        assert set(self._widgets()) <= {
            "heading", "text-editor", "image", "button", "icon-list", "divider"}

    def test_headings_keep_their_level(self) -> None:
        tree, _n = build_document(_page())
        heads = []

        def walk(nodes: list[dict[str, Any]]) -> None:
            for n in nodes:
                if n.get("widgetType") == "heading":
                    heads.append(n["settings"]["header_size"])
                walk(n.get("elements") or [])

        walk(tree)
        assert heads == ["h1", "h2"], "an h1 rebuilt as an h2 changes the page's outline"

    def test_a_marked_link_becomes_a_button_carrying_its_href(self) -> None:
        tree, _n = build_document(_page())
        btn: dict[str, Any] = {}

        def walk(nodes: list[dict[str, Any]]) -> None:
            nonlocal btn
            for n in nodes:
                if n.get("widgetType") == "button":
                    btn = n["settings"]
                walk(n.get("elements") or [])

        walk(tree)
        assert btn["text"] == "Explore the collection"
        assert btn["link"]["url"] == "https://spotino.org/collection"

    def test_a_plain_link_is_not_promoted_to_a_button(self) -> None:
        """Guessing from position or wording gives a page full of "buttons" that were
        really navigation links."""
        html = '<main><p>See our <a href="/x">collection page</a> today.</p></main>'
        assert not [b for b in capture_html(html).blocks if b.kind == "button"]

    def test_a_list_becomes_an_icon_list_with_every_item(self) -> None:
        tree, _n = build_document(_page())
        items: list[Any] = []

        def walk(nodes: list[dict[str, Any]]) -> None:
            for n in nodes:
                if n.get("widgetType") == "icon-list":
                    items.extend(n["settings"]["icon_list"])
                walk(n.get("elements") or [])

        walk(tree)
        assert [i["text"] for i in items] == ["Kiln-dried frame", "Ten-year warranty"]

    def test_every_node_has_an_id(self) -> None:
        """Elementor keys its editor state off these; a node without one is unselectable."""
        tree, _n = build_document(_page())

        def walk(nodes: list[dict[str, Any]]) -> bool:
            return all(n.get("id") and walk(n.get("elements") or []) is not False
                       for n in nodes)

        assert walk(tree) is not False

    def test_the_structure_is_section_column_widget(self) -> None:
        tree, _n = build_document(_page())
        assert tree[0]["elType"] == "section"
        assert tree[0]["elements"][0]["elType"] == "column"
        assert tree[0]["elements"][0]["elements"][0]["elType"] == "widget"


class TestStyling:
    def test_measured_typography_beats_the_pages_font_links(self) -> None:
        """Same rule the brand kit merges by: a real browser measurement beats a guess."""
        style = style_from(_page(), {"typography": {"heading_font": "Bricolage Grotesque"}})
        assert style["heading_font"] == "Bricolage Grotesque"

    def test_without_measurement_the_pages_own_fonts_are_used(self) -> None:
        assert style_from(_page())["heading_font"] in ("Raleway", "Roboto")

    def test_typography_is_switched_to_custom_or_elementor_ignores_it(self) -> None:
        """`*_typography_typography = "custom"` is the switch Elementor's UI uses. Without
        it the font keys are stored and ignored - the editor shows the global font while
        the page renders ours."""
        tree, _n = build_document(_page(), measured={"typography": {"heading_font": "X"}})
        found: dict[str, Any] = {}

        def walk(nodes: list[dict[str, Any]]) -> None:
            for n in nodes:
                if n.get("widgetType") == "heading":
                    found.update(n["settings"])
                walk(n.get("elements") or [])

        walk(tree)
        assert found.get("title_typography_typography") == "custom"
        assert found.get("title_typography_font_family") == "X"


class TestHonestyAboutWhatCameAcross:
    def test_placeholder_images_are_reported_not_hidden(self) -> None:
        """MEASURED on the real page: all 23 images were Elementor's placeholder. "your
        images did not come across" and "your page has no images" are different problems
        with different fixes, so the note says which."""
        html = _PAGE.replace('data-src="/img/sofa.jpg"',
                             f'data-src="/wp-content/plugins/{PLACEHOLDER_MARKER}.png"')
        _tree, notes = build_document(capture_html(html, base_url="https://x.test/"))
        assert any("placeholder" in n for n in notes)

    def test_an_empty_document_says_so_rather_than_returning_nothing(self) -> None:
        _tree, notes = build_document(capture_html("<html><body></body></html>"))
        assert any("nothing was rebuilt" in n for n in notes)

    def test_a_missing_meta_description_is_flagged_at_capture(self) -> None:
        html = _PAGE.replace('<meta name="description" content="Handmade sofas built to order." />', "")
        assert any("no meta description" in n for n in capture_html(html).notes)

    def test_malformed_markup_does_not_raise(self) -> None:
        """A client's page is not ours to validate."""
        for bad in ("<main><h1>unclosed", "<<>>", "<main><p>a</div></p></main>", ""):
            capture_html(bad)


class TestMeta:
    def test_the_head_metadata_is_carried(self) -> None:
        meta = meta_payload(_page())
        assert meta["title"] == "hy - SPOTiNO"
        assert meta["description"] == "Handmade sofas built to order."
        assert meta["canonical"] == "https://spotino.org/hy/"
        assert meta["og_image"] == "https://spotino.org/img/og.jpg"

    def test_og_falls_back_to_the_page_title_and_description(self) -> None:
        meta = meta_payload(_page())
        assert meta["og_title"] == "hy - SPOTiNO"
        assert meta["og_description"] == "Handmade sofas built to order."

    def test_fonts_the_page_loads_are_recorded(self) -> None:
        assert set(_page().meta.fonts) == {"Roboto", "Raleway"}

    def test_meta_is_not_emitted_as_a_widget(self) -> None:
        """Title and description belong in the head, and the SEO plugin's own box is
        where an operator expects to edit them."""
        tree, _n = build_document(_page())
        assert "hy - SPOTiNO" not in str(tree)
