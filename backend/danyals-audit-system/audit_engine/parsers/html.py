"""HTML parser. BeautifulSoup wrapper extracting the fields every on-page
analyzer needs: title, meta description, canonical, robots meta, H1s, H2-H6
outline, internal/external links, images, JSON-LD schema blocks, OpenGraph,
hreflang, llms.txt hint, and rough word count.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


@dataclass
class Heading:
    level: int  # 1-6
    text: str


@dataclass
class Link:
    href: str
    anchor_text: str
    rel: list[str]
    is_internal: bool
    is_nofollow: bool


@dataclass
class Image:
    src: str
    alt: str | None
    width: str | None
    height: str | None
    loading: str | None
    is_lazy: bool


@dataclass
class HreflangEntry:
    lang: str
    href: str


@dataclass
class ParsedHTML:
    url: str
    title: str | None = None
    title_length: int = 0
    meta_description: str | None = None
    meta_description_length: int = 0
    meta_robots: str | None = None
    canonical: str | None = None
    h1s: list[str] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    schema_blocks: list[dict] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    opengraph: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    hreflang: list[HreflangEntry] = field(default_factory=list)
    viewport: str | None = None
    lang: str | None = None
    word_count: int = 0
    raw_html_bytes: int = 0
    has_amp: bool = False
    has_noindex: bool = False
    has_nofollow_meta: bool = False
    body_text: str = ""
    paragraphs: list[str] = field(default_factory=list)
    paragraph_word_counts: list[int] = field(default_factory=list)
    list_count: int = 0
    ordered_list_count: int = 0
    table_count: int = 0
    button_texts: list[str] = field(default_factory=list)
    form_count: int = 0
    nav_link_count: int = 0
    semantic_tag_counts: dict[str, int] = field(default_factory=dict)
    has_breadcrumb_nav: bool = False
    # Structural extras
    rel_next: str | None = None
    rel_prev: str | None = None
    footer_links: list[Link] = field(default_factory=list)
    footer_link_count: int = 0
    bylines: list[str] = field(default_factory=list)
    has_about_page_link: bool = False
    has_contact_page_link: bool = False


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    return tag.get_text(strip=True) or None


def _attr(tag: Tag | None, name: str) -> str | None:
    if tag is None:
        return None
    val = tag.get(name)
    if isinstance(val, list):
        return " ".join(val)
    return val if val is None else str(val)


def parse(html: str, url: str) -> ParsedHTML:
    soup = BeautifulSoup(html, "lxml")
    out = ParsedHTML(url=url, raw_html_bytes=len(html.encode("utf-8", errors="replace")))

    # <html lang>
    html_tag = soup.find("html")
    if html_tag and isinstance(html_tag, Tag):
        out.lang = _attr(html_tag, "lang")

    # Title
    title_tag = soup.find("title")
    out.title = _text(title_tag)
    out.title_length = len(out.title or "")

    # Meta description, robots, viewport
    for meta in soup.find_all("meta"):
        if not isinstance(meta, Tag):
            continue
        name = (meta.get("name") or "").lower() if isinstance(meta.get("name"), str) else ""
        prop = (meta.get("property") or "").lower() if isinstance(meta.get("property"), str) else ""
        content = meta.get("content") or ""
        if isinstance(content, list):
            content = " ".join(content)
        content = str(content)
        if name == "description":
            out.meta_description = content
            out.meta_description_length = len(content)
        elif name == "robots":
            out.meta_robots = content
            ctl = content.lower()
            if "noindex" in ctl:
                out.has_noindex = True
            if "nofollow" in ctl:
                out.has_nofollow_meta = True
        elif name == "viewport":
            out.viewport = content
        elif prop.startswith("og:"):
            out.opengraph[prop] = content
        elif name.startswith("twitter:"):
            out.twitter[name] = content

    # Canonical
    canonical_tag = soup.find("link", rel="canonical")
    out.canonical = _attr(canonical_tag, "href")

    # Hreflang
    for link in soup.find_all("link", rel="alternate"):
        if not isinstance(link, Tag):
            continue
        hreflang = _attr(link, "hreflang")
        href = _attr(link, "href")
        if hreflang and href:
            out.hreflang.append(HreflangEntry(lang=hreflang, href=href))

    # AMP
    if soup.find("link", rel="amphtml") is not None or (
        html_tag and isinstance(html_tag, Tag) and (html_tag.has_attr("amp") or html_tag.has_attr("⚡"))
    ):
        out.has_amp = True

    # Headings
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if not text:
                continue
            out.headings.append(Heading(level=level, text=text))
            if level == 1:
                out.h1s.append(text)

    # Links
    parsed_base = urlparse(url)
    base_host = parsed_base.netloc.lower()
    for a in soup.find_all("a"):
        if not isinstance(a, Tag):
            continue
        href = _attr(a, "href")
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(url, href)
        rel_raw = a.get("rel") or []
        rel = [r.lower() for r in (rel_raw if isinstance(rel_raw, list) else [rel_raw])]
        is_internal = urlparse(absolute).netloc.lower() == base_host
        out.links.append(
            Link(
                href=absolute,
                anchor_text=a.get_text(strip=True),
                rel=rel,
                is_internal=is_internal,
                is_nofollow="nofollow" in rel,
            )
        )

    # Navigation (for UX and breadcrumb heuristics)
    nav = soup.find("nav")
    if isinstance(nav, Tag):
        out.nav_link_count = len(nav.find_all("a"))
        aria = nav.get("aria-label") or ""
        if isinstance(aria, list):
            aria = " ".join(aria)
        if "breadcrumb" in str(aria).lower():
            out.has_breadcrumb_nav = True

    # Images
    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue
        src = _attr(img, "src") or _attr(img, "data-src")
        if not src:
            continue
        loading = _attr(img, "loading")
        out.images.append(
            Image(
                src=urljoin(url, src),
                alt=_attr(img, "alt"),
                width=_attr(img, "width"),
                height=_attr(img, "height"),
                loading=loading,
                is_lazy=loading == "lazy",
            )
        )

    # Paragraphs and lists
    for p in soup.find_all("p"):
        if not isinstance(p, Tag):
            continue
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        out.paragraphs.append(text)
        out.paragraph_word_counts.append(len(_WORD_RE.findall(text)))

    out.list_count = len(soup.find_all("ul"))
    out.ordered_list_count = len(soup.find_all("ol"))
    out.table_count = len(soup.find_all("table"))

    for btn in soup.find_all(["button", "a"]):
        if not isinstance(btn, Tag):
            continue
        role = (btn.get("role") or "")
        if isinstance(role, list):
            role = " ".join(role)
        if btn.name == "button" or (btn.name == "a" and "button" in str(role).lower()):
            text = btn.get_text(" ", strip=True)
            if text:
                out.button_texts.append(text)

    out.form_count = len(soup.find_all("form"))

    # Semantic HTML tag usage
    for tag_name in ("article", "section", "figure", "figcaption", "time", "main", "aside", "header", "footer", "nav"):
        out.semantic_tag_counts[tag_name] = len(soup.find_all(tag_name))

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        if not isinstance(script, Tag) or not script.string:
            continue
        try:
            block = json.loads(script.string)
            if isinstance(block, list):
                out.schema_blocks.extend([b for b in block if isinstance(b, dict)])
            elif isinstance(block, dict):
                out.schema_blocks.append(block)
        except json.JSONDecodeError as e:
            out.schema_errors.append(f"JSON-LD: {e.msg} at pos {e.pos}")

    # rel=next / rel=prev pagination
    for link in soup.find_all("link"):
        if not isinstance(link, Tag):
            continue
        rel = link.get("rel") or []
        rel_list = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
        href = _attr(link, "href")
        if not href:
            continue
        if "next" in rel_list and out.rel_next is None:
            out.rel_next = urljoin(url, href)
        if "prev" in rel_list and out.rel_prev is None:
            out.rel_prev = urljoin(url, href)

    # Footer link extraction (before decomposing scripts)
    footer = soup.find("footer")
    if isinstance(footer, Tag):
        for a in footer.find_all("a"):
            if not isinstance(a, Tag):
                continue
            href = _attr(a, "href")
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            absolute = urljoin(url, href)
            rel_raw = a.get("rel") or []
            rel = [r.lower() for r in (rel_raw if isinstance(rel_raw, list) else [rel_raw])]
            is_internal = urlparse(absolute).netloc.lower() == base_host
            out.footer_links.append(
                Link(
                    href=absolute,
                    anchor_text=a.get_text(strip=True),
                    rel=rel,
                    is_internal=is_internal,
                    is_nofollow="nofollow" in rel,
                )
            )
        out.footer_link_count = len(out.footer_links)

    # About / Contact page link detection (anywhere on the page)
    about_terms = ("about", "about-us", "about us", "who-we-are")
    contact_terms = ("contact", "contact-us", "contact us", "get in touch", "reach us")
    for link in out.links:
        href_lc = link.href.lower()
        anchor_lc = (link.anchor_text or "").lower().strip()
        if any(t in href_lc for t in ("/about", "/about-us")) or anchor_lc in about_terms:
            out.has_about_page_link = True
        if any(t in href_lc for t in ("/contact", "/contact-us")) or anchor_lc in contact_terms:
            out.has_contact_page_link = True
        if out.has_about_page_link and out.has_contact_page_link:
            break

    # Byline detection (look for "By <Name>" patterns and rel=author links)
    # Limit to common elements where author bylines appear.
    byline_re = re.compile(r"\bby\s+([A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+){0,3})\b")
    for selector in ("[rel='author']", ".author", ".byline", "[class*='author']", "[class*='byline']"):
        try:
            for tag in soup.select(selector):
                t = tag.get_text(" ", strip=True)
                if t and 2 < len(t) < 120:
                    out.bylines.append(t)
        except Exception:  # noqa: BLE001
            pass
    # Heuristic byline regex on first ~3 paragraphs only (cheap, low FP)
    for p_tag in soup.find_all("p", limit=8):
        if not isinstance(p_tag, Tag):
            continue
        text = p_tag.get_text(" ", strip=True)
        if not text or len(text) > 300:
            continue
        m = byline_re.search(text)
        if m:
            out.bylines.append(m.group(0))
    # Dedupe + cap
    out.bylines = list(dict.fromkeys(out.bylines))[:5]

    # Word count - drop scripts, styles, navs to approximate visible content.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ", strip=True)
    out.word_count = len(_WORD_RE.findall(visible_text))
    # Cap body_text at ~50k chars; analyzers only need it for shingle hashing
    # and readability sampling, not full retention.
    out.body_text = visible_text[:50000]

    return out
