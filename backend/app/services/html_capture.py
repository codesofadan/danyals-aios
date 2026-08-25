"""Parse a rendered page into semantic blocks (P6.6, step 1 of 2).

WHY THIS EXISTS. `site_analyzer` measures a page - computed styles, section boxes,
asset URLs - and `site_design` describes it. Neither REPRODUCES it: nothing turns the
page a client points at into a structure we can re-emit as editable widgets. That is
the gap between "we looked at your site" and "here is your site, rebuilt and editable".

STDLIB ONLY. `html.parser.HTMLParser`, exactly as `on_page/service.py` already does. A
real page is 400KB of theme chrome, scripts and inline SVG, and pulling in lxml or
BeautifulSoup for it would add a compiled dependency to a base install this project has
kept deliberately light.

WHAT IT DELIBERATELY DOES NOT DO. It does not resolve the CSS cascade. Knowing that an
<h2> renders at 34px Bricolage Grotesque requires the stylesheet, the media query and
the specificity chain, and guessing at it produces a page that looks almost right in a
way nobody can debug. Typography comes from `site_analyzer`'s real getComputedStyle
measurements instead, which is what that module is FOR. What this reads is what the
markup itself states: structure, text, links, images, and inline style declarations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

# Content that is never page content.
_SKIP_CONTENT = frozenset({"script", "style", "noscript", "template", "svg", "canvas"})

# Chrome that belongs to the theme, not to the page a client asked us to rebuild.
# Reproducing a site's header and footer as page widgets would duplicate them on every
# page and fight whatever the theme already renders.
_CHROME = frozenset({"header", "nav", "footer", "aside"})

# THE CONTENT ROOT, and why tag-based chrome detection is not enough on its own.
#
# Measured on a real Elementor page: the site's logo and primary navigation are plain
# <div>s, not <header>/<nav>. Skipping by tag therefore captured "Skip to main content",
# the logo letters "A / AM SOFA / AM SOFA STUDIO" and the theme's page-title <h1> as
# page content - the rebuild would have opened with the client's own chrome duplicated
# inside the body.
#
# An Elementor page states its own boundary: `data-elementor-type="wp-page"` wraps
# exactly the content the page owns. That is the most reliable root available, so it is
# preferred; <main> and <article> are the fallbacks for a page not built with Elementor.
_ROOT_ATTR = ("data-elementor-type", ("wp-page", "wp-post", "page", "post"))
_ROOT_TAGS = ("main", "article")

# Accessibility skip links are real <a> elements and never page content.
_SKIP_LINK = re.compile(r"skip to (main )?content|skip navigation", re.I)

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_INLINE = frozenset({"a", "strong", "b", "em", "i", "u", "span", "small", "mark",
                     "sup", "sub", "code", "br"})
_BLOCK_BREAK = frozenset({"p", "div", "section", "li", "td", "blockquote", "figcaption",
                          *_HEADINGS})

# A link is a BUTTON when the markup says so. Guessing from position or wording gives a
# page full of "buttons" that were really navigation links.
_BUTTON_HINT = re.compile(
    r"\b(btn|button|cta|elementor-button|wp-block-button__link)\b", re.I
)


@dataclass
class Block:
    """One semantic thing on the page."""

    kind: str  # heading | text | image | button | list | divider | quote
    text: str = ""
    level: int = 0
    url: str = ""
    alt: str = ""
    items: list[str] = field(default_factory=list)
    styles: dict[str, str] = field(default_factory=dict)
    section: int = 0

    def is_empty(self) -> bool:
        return not (self.text.strip() or self.url or self.items)


@dataclass
class PageMeta:
    """Everything that belongs in the page's head rather than its body."""

    title: str = ""
    description: str = ""
    canonical: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    lang: str = ""
    fonts: tuple[str, ...] = ()


@dataclass
class CapturedPage:
    meta: PageMeta = field(default_factory=PageMeta)
    blocks: list[Block] = field(default_factory=list)
    notes: tuple[str, ...] = ()

    def by_section(self) -> list[list[Block]]:
        out: dict[int, list[Block]] = {}
        for b in self.blocks:
            out.setdefault(b.section, []).append(b)
        return [out[k] for k in sorted(out)]


def _parse_style(raw: str) -> dict[str, str]:
    """Inline `style="..."` declarations. What the markup STATES, not what it computes."""
    out: dict[str, str] = {}
    for part in (raw or "").split(";"):
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        name, value = name.strip().lower(), value.strip()
        if name and value:
            out[name] = value
    return out


def _best_src(attrs: dict[str, str], base: str) -> str:
    """The real image URL, accounting for lazy-loading.

    An Elementor page routinely ships `src="data:image/svg+xml,..."` as a placeholder
    with the real file in `data-src` or `srcset`. Taking `src` naively reproduces the
    page with every image replaced by a grey rectangle.
    """
    for key in ("data-src", "data-lazy-src", "data-original"):
        if attrs.get(key):
            return urljoin(base, attrs[key])
    srcset = attrs.get("srcset") or attrs.get("data-srcset") or ""
    if srcset:
        # Widest candidate: the page's own highest-resolution version of the asset.
        best, best_w = "", -1
        for candidate in srcset.split(","):
            bits = candidate.strip().split()
            if not bits:
                continue
            width = 0
            if len(bits) > 1 and bits[1].endswith("w"):
                try:
                    width = int(bits[1][:-1])
                except ValueError:
                    width = 0
            if width > best_w:
                best, best_w = bits[0], width
        if best:
            return urljoin(base, best)
    src = attrs.get("src") or ""
    if src.startswith("data:"):
        return ""  # a placeholder is not an image
    return urljoin(base, src) if src else ""


class _Parser(HTMLParser):
    """Walks the document once, emitting blocks in document order."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.meta = PageMeta()
        self.blocks: list[Block] = []
        self._skip_depth = 0
        self._chrome_depth = 0
        self._depth = 0
        # Once a root is found, only its subtree is captured. Until then nothing is,
        # unless the document turns out to have no root at all (see `capture_html`).
        self._root_depth: int | None = None
        self._root_kind = ""
        self._text: list[str] = []
        self._mode = ""          # heading | text | button | quote
        self._level = 0
        self._href = ""
        self._styles: dict[str, str] = {}
        self._list: list[str] | None = None
        self._li: list[str] = []
        self._section = 0
        self._title = False
        self._fonts: set[str] = set()
        self._maybe_skip_link = False

    # --- text accumulation ------------------------------------------------- #
    def _capturing(self) -> bool:
        return self._root_depth is not None and not self._chrome_depth

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._title:
            self.meta.title += data
            return
        if not self._capturing():
            return
        if self._list is not None:
            self._li.append(data)
        elif self._mode:
            self._text.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        # An accessibility skip link is an <a> whose class rarely says so but whose
        # TEXT always does. It is never page content, and reproducing it puts a stray
        # "Skip to main content" button at the top of the rebuilt page.
        if self._mode == "button" and _SKIP_LINK.search(text):
            self._text, self._mode, self._level, self._href = [], "", 0, ""
            self._styles = {}
            return
        if text and self._mode:
            self.blocks.append(Block(
                kind=self._mode, text=text, level=self._level, url=self._href,
                styles=dict(self._styles), section=self._section,
            ))
        self._text, self._mode, self._level, self._href = [], "", 0, ""
        self._styles = {}

    # --- tags -------------------------------------------------------------- #
    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "html" and attrs.get("lang"):
            self.meta.lang = attrs["lang"]
        if tag == "title":
            self._title = True
            return
        if tag == "link":
            self._read_link(attrs)
            return
        if tag == "meta":
            self._read_meta(attrs)
            return

        # Depth is tracked for every element so the root's own close can be recognised.
        void = tag in ("br", "hr", "img", "input", "meta", "link", "source", "area")
        if not void:
            self._depth += 1

        if self._root_depth is None:
            attr_name, accepted = _ROOT_ATTR
            if attrs.get(attr_name, "").strip().lower() in accepted or tag in _ROOT_TAGS:
                self._root_depth = self._depth
                self._root_kind = attrs.get(attr_name) or tag
            return

        if tag in _CHROME:
            # Chrome nested inside the content root is page content (a card's <aside>),
            # so this only fires for chrome the root itself contains.
            self._chrome_depth += 1
            return
        if self._chrome_depth:
            return

        if tag == "section":
            self._flush()
            self._section += 1
            return
        if tag == "hr":
            self._flush()
            self.blocks.append(Block(kind="divider", section=self._section))
            return
        if tag == "img":
            url = _best_src(attrs, self.base)
            if url:
                self._flush()
                self.blocks.append(Block(
                    kind="image", url=url, alt=unescape(attrs.get("alt") or ""),
                    styles=_parse_style(attrs.get("style", "")), section=self._section,
                ))
            return
        if tag in ("ul", "ol"):
            self._flush()
            self._list = []
            return
        if tag == "li" and self._list is not None:
            self._li = []
            return
        if tag in _HEADINGS:
            self._flush()
            self._mode, self._level = "heading", _HEADINGS[tag]
            self._styles = _parse_style(attrs.get("style", ""))
            return
        if tag == "blockquote":
            self._flush()
            self._mode = "quote"
            return
        if tag == "a":
            classes = attrs.get("class", "")
            if attrs.get("href", "").startswith("#") and _SKIP_LINK.search(classes):
                return
            self._maybe_skip_link = attrs.get("href", "").startswith("#")
            if _BUTTON_HINT.search(classes) or attrs.get("role") == "button":
                self._flush()
                self._mode = "button"
                self._href = urljoin(self.base, attrs.get("href", ""))
                self._styles = _parse_style(attrs.get("style", ""))
            return
        if tag == "button":
            self._flush()
            self._mode = "button"
            return
        if tag in _BLOCK_BREAK and self._mode not in ("heading", "button"):
            self._flush()
            self._mode = "text"
            self._styles = _parse_style(attrs.get("style", ""))
            return
        if tag == "br" and self._mode:
            self._text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title = False
            self.meta.title = re.sub(r"\s+", " ", self.meta.title).strip()
            return
        void = tag in ("br", "hr", "img", "input", "meta", "link", "source", "area")

        if self._root_depth is not None and not void and self._depth == self._root_depth:
            # The root element itself closed: everything after it is chrome again.
            self._flush()
            self._root_depth = None
            self._depth -= 1
            return

        if self._root_depth is not None and tag in _CHROME:
            self._chrome_depth = max(0, self._chrome_depth - 1)
            if not void:
                self._depth -= 1
            return
        if not self._capturing():
            if not void:
                self._depth = max(0, self._depth - 1)
            return
        if not void:
            self._depth -= 1
        if tag == "li" and self._list is not None:
            item = re.sub(r"\s+", " ", "".join(self._li)).strip()
            if item:
                self._list.append(item)
            self._li = []
            return
        if tag in ("ul", "ol"):
            if self._list:
                self.blocks.append(Block(
                    kind="list", items=list(self._list), section=self._section
                ))
            self._list = None
            return
        if tag in _HEADINGS or tag in ("blockquote", "a", "button", *_BLOCK_BREAK):
            self._flush()

    # --- head ------------------------------------------------------------- #
    def _read_meta(self, attrs: dict[str, str]) -> None:
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = unescape(attrs.get("content") or "").strip()
        if not content:
            return
        if name == "description":
            self.meta.description = content
        elif name == "og:title":
            self.meta.og_title = content
        elif name == "og:description":
            self.meta.og_description = content
        elif name == "og:image":
            self.meta.og_image = urljoin(self.base, content)

    def _read_link(self, attrs: dict[str, str]) -> None:
        rel = (attrs.get("rel") or "").lower()
        href = attrs.get("href") or ""
        if rel == "canonical" and href:
            self.meta.canonical = href
        if "fonts.googleapis.com" in href:
            for family in re.findall(r"family=([^&]+)", href):
                for one in family.split("|"):
                    name = one.split(":")[0].replace("+", " ").strip()
                    if name:
                        self._fonts.add(name)


def capture_html(html: str, *, base_url: str = "") -> CapturedPage:
    """Parse a rendered page into ordered semantic blocks plus its head metadata.

    Total: never raises on malformed markup - `HTMLParser` is tolerant by design, and a
    client's page is not ours to validate.
    """
    parser = _Parser(base_url=base_url)
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # a pathological document must not lose what was parsed already
        pass
    parser._flush()

    blocks = [b for b in parser.blocks if not b.is_empty()]
    meta = parser.meta
    meta.fonts = tuple(sorted(parser._fonts))

    notes: list[str] = []
    if not blocks:
        notes.append("no content blocks were found outside the theme's header/footer")
    if not meta.description:
        notes.append("the page has no meta description")
    return CapturedPage(meta=meta, blocks=blocks, notes=tuple(notes))
