"""On-page analysis - the PURE detector core + the tool-workspace adapter.

This module is DB-free and network-free (mirrors ``keyword_research.service`` /
``content_research``'s pure core): it takes already-fetched HTML (or an already-run
audit's findings) and turns it into recommendations - deterministic given the same
input. The SSRF-guarded fetch, the cost gate, and the live-site writes live in
``tasks.py``; the RLS reads live in ``repo.py``; this layer just reasons.

THE THRESHOLDS ARE NAMED CONSTANTS, NOT MAGIC NUMBERS. Every one is a 2026
industry-consensus figure and is stated once, at the top, with the reasoning that
justifies it - so recalibrating the engine is a one-line edit and a reviewer can
audit the judgement rather than reverse-engineer it from a comparison.

IT REUSES THE PART-7 CONTENT ENGINE INSTEAD OF REINVENTING IT. The content score is
``content_qa``'s rubric applied to a live page: ``_covered_entities`` for entity
coverage, the ``content_generator`` density bands for keyword handling, and
``flesch_reading_ease`` for readability. There is exactly ONE content rubric in this
codebase and this module does not fork it.

IT DEGRADES HONESTLY. Entity coverage needs a SERP teardown (Serper) and the judge
dimensions need Anthropic; with no keys those sub-scores are OMITTED and the result
is flagged ``degraded`` with the reason - the deterministic sub-scores still score.
It never invents a number it could not measure, and it never crashes for want of a
key.

``build_workspace`` is the ``GET /on-page/workspace`` adapter: it emits the frontend
``lib/tools.ts`` ``on_page`` EXTRA shape with table columns pinned EXACTLY to
``["Page", "Issue", "Impact", "Status"]`` (the tool-workspace contract test asserts
this byte-for-byte).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from app.modules.on_page.schemas import OnPageStats
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)
from app.services.content_generator import (
    PRIMARY_DENSITY_HARD_CEILING,
    PRIMARY_DENSITY_TARGET_MAX,
    PRIMARY_DENSITY_TARGET_MIN,
)
from app.services.content_qa import _covered_entities, flesch_reading_ease

# --------------------------------------------------------------------------- #
# The 2026 thresholds. Every number below is stated ONCE, here.
# --------------------------------------------------------------------------- #
# Title: Google truncates the SERP title at ~600px, not at a character count. 30-60
# characters is the industry-consensus proxy (~285-580px at the SERP's ~9.6px average
# glyph width), so a title inside this band renders in full on desktop AND mobile.
# Below 30 the title is under-using the single strongest on-page ranking element.
TITLE_MIN_CHARS = 30
TITLE_MAX_CHARS = 60
TITLE_MIN_PIXELS = 285  # the ~px equivalents, recorded as evidence on the finding
TITLE_MAX_PIXELS = 580

# Meta description: not a ranking factor, but it IS the SERP ad copy and drives CTR.
# Google truncates around ~920px desktop / ~680px mobile; 120-160 characters is the
# band that fills the snippet without being cut mid-sentence.
META_MIN_CHARS = 120
META_MAX_CHARS = 160

# Exactly one H1: HTML5 permits multiple, but a single H1 remains the unambiguous
# topical signal, and Google's own guidance treats it as the page's headline.
H1_EXPECTED_COUNT = 1

# Thin content: ~300 words is the floor below which a page rarely demonstrates the
# depth to satisfy an informational intent. It is a FLOOR, not a target - it flags
# pages that cannot compete, it does not reward padding.
THIN_CONTENT_MIN_WORDS = 300

# Internal links: >= 2 contextual internal links per ~1000 words. Fewer and the page
# is a dead end for both crawlers and equity flow.
INTERNAL_LINKS_PER_1000_WORDS = 2.0

# Flesch reading ease: the content doctrine (§11.11) targets ~60-70 (plain,
# people-first English). Below 45 the prose is measurably hard going for a general
# audience, which is where we raise a finding rather than a preference.
READABILITY_MIN_FLESCH = 45.0

# The content score (0-100) below which the page gets an explicit `content_score_low`
# recommendation of its own, over and above the individual findings.
CONTENT_SCORE_FLOOR = 70.0

# --------------------------------------------------------------------------- #
# Impact / effort model
# --------------------------------------------------------------------------- #
# The DEFAULT impact per issue code. A finding ingested from an audit run overrides
# these from the engine's own `severity` (see `_SEVERITY_IMPACT`).
_ISSUE_IMPACT: dict[str, str] = {
    # Title - the strongest on-page element; a missing or off-keyword title is High.
    "title_missing": "High",
    "title_keyword_missing": "High",
    "title_short": "Med",
    "title_long": "Med",
    "title_no_brand": "Low",
    # Meta - CTR, not rank: High only when absent entirely.
    "meta_missing": "High",
    "meta_duplicate": "Med",
    "meta_short": "Med",
    "meta_long": "Med",
    # Headings.
    "h1_missing": "High",
    "h1_multiple": "Med",
    "h1_keyword_missing": "Med",
    "heading_hierarchy_skip": "Low",
    # Body.
    "thin_content": "High",
    "duplicate_content": "High",
    "content_score_low": "Med",
    "keyword_density_high": "Med",  # stuffing risks a penalty
    "keyword_density_low": "Low",
    "readability_low": "Low",
    # Structure / markup.
    "canonical_conflict": "High",  # points elsewhere = actively de-indexing this page
    "canonical_missing": "Med",
    "schema_missing": "Med",
    "schema_invalid": "Med",
    "internal_link_orphan": "High",
    "internal_links_few": "Med",
    "image_alt_missing": "Low",
}

# How each issue's fix is DELIVERED. title/meta/schema are the machine-applicable
# ones; heading/content need judgement about the page's prose; `manual` is work only
# a human can do (or work that lives outside the post: canonical + alt text are
# plugin/media-library concerns, not post fields).
_ISSUE_FIX_KIND: dict[str, str] = {
    "title_missing": "title",
    "title_short": "title",
    "title_long": "title",
    "title_keyword_missing": "title",
    "title_no_brand": "title",
    "meta_missing": "meta",
    "meta_short": "meta",
    "meta_long": "meta",
    "meta_duplicate": "meta",
    "h1_missing": "heading",
    "h1_multiple": "heading",
    "h1_keyword_missing": "heading",
    "heading_hierarchy_skip": "heading",
    "schema_missing": "schema",
    "schema_invalid": "schema",
    "thin_content": "content",
    "duplicate_content": "manual",
    "content_score_low": "content",
    "readability_low": "content",
    "keyword_density_low": "content",
    "keyword_density_high": "content",
    "internal_links_few": "content",
    "internal_link_orphan": "manual",
    "image_alt_missing": "manual",
    "canonical_missing": "manual",
    "canonical_conflict": "manual",
}

# Impact x Effort. Impact is the upside; effort is the cost of realising it.
_IMPACT_WEIGHT: dict[str, float] = {"High": 3.0, "Med": 2.0, "Low": 1.0}
_EFFORT: dict[str, float] = {
    "title": 1.0, "meta": 1.0, "schema": 1.0,  # one field, machine-applicable
    "heading": 2.0,                             # touches the page's structure
    "content": 3.0,                             # touches the prose
    "manual": 4.0,                              # a human has to do it
}
# The fix kinds we can apply without a human writing anything.
_LOW_EFFORT_KINDS: frozenset[str] = frozenset({"title", "meta", "schema"})
MANUAL_FIX_KIND = "manual"

# The audit engine's severity vocabulary -> our 3-band impact. `critical` and `major`
# both land on High: the engine's split is about remediation urgency, ours is about
# the size of the win, and both of its top bands are wins worth taking first.
_SEVERITY_IMPACT: dict[str, str] = {
    "critical": "High",
    "major": "High",
    "minor": "Med",
    "info": "Low",
}

# The 363-check engine's on-page checks -> our issue taxonomy. Where an audit run
# EXISTS we map its findings rather than re-detecting them: the engine already
# crawled the page with more context (the SERP, the site graph, GSC) than a
# single-page fetch can ever have. Only checks with an unambiguous 1:1 meaning are
# mapped; the rest stay the engine's to report.
_CHECK_ISSUE: dict[str, str] = {
    "ON-023": "thin_content",
    "ON-034": "title_short",             # "Title tag optimization" (length/quality)
    "ON-037": "title_keyword_missing",   # "Title keyword placement"
    "ON-038": "meta_missing",            # "Meta description optimization"
    "ON-040": "meta_duplicate",          # "Meta description uniqueness"
    "ON-041": "h1_missing",              # "H1 optimization"
    "ON-042": "h1_multiple",             # "Multiple H1 detection"
    "ON-043": "heading_hierarchy_skip",  # "Heading hierarchy analysis"
    "ON-051": "readability_low",         # "Content readability analysis"
    "ON-059": "internal_links_few",      # "Internal link relevance"
    "ON-060": "internal_link_orphan",    # "Internal link depth analysis"
    "ON-067": "image_alt_missing",       # "Image alt text optimization"
    "ON-073": "schema_invalid",          # "Schema markup validation"
    "ON-079": "canonical_missing",       # "Canonical tag validation (on-page)"
    "ON-095": "duplicate_content",       # "Duplicate content detection"
    "ON-109": "keyword_density_high",    # "Over optimization penalty detection"
}
# Only a failing/warning check is a recommendation; a `pass` is not work to do.
_ACTIONABLE_STATUSES: frozenset[str] = frozenset({"fail", "warn"})

# --- tool-workspace contract constants (pinned to lib/tools.ts on_page) -------
WORKSPACE_TABLE_COLS: list[str] = ["Page", "Issue", "Impact", "Status"]
_WORKSPACE_TABLE_TITLE = "Top recommendations"
_WORKSPACE_TABLE_ICON = "tune"
_WORKSPACE_PRIMARY = ToolPrimary(label="Analyze page", icon="tune")
_WORKSPACE_BULLETS = [
    "Review on-page recommendations",
    "Apply title, meta & heading fixes",
    "Score content against target keywords",
]
_WORKSPACE_ROW_LIMIT = 8

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# The parsed page
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Heading:
    """One heading in document order."""

    level: int
    text: str


@dataclass(frozen=True)
class ParsedPage:
    """Everything the detectors read off ONE fetched page. Purely descriptive: it
    records what the page HAS, never a judgement about it."""

    url: str = ""
    title: str = ""
    meta_description: str = ""
    robots: str = ""
    canonical: str = ""
    headings: list[Heading] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    images_total: int = 0
    images_missing_alt: int = 0
    json_ld_raw: list[str] = field(default_factory=list)
    body_text: str = ""

    @property
    def word_count(self) -> int:
        return len(_WORD_RE.findall(self.body_text))

    @property
    def h1s(self) -> list[Heading]:
        return [h for h in self.headings if h.level == 1]


class _PageHtmlParser(HTMLParser):
    """A stdlib HTML parser that harvests every on-page signal in ONE pass.

    ``html.parser`` rather than a regex sweep (the technique ``content_research``
    uses for its coarser needs) because on-page analysis turns on ATTRIBUTES - an
    ``img`` with ``alt=""`` vs no ``alt`` at all, ``rel="canonical"`` vs
    ``rel="alternate"`` - and attribute-accurate regex over real-world HTML is a
    losing game. It is stdlib, so this stays dependency-free either way.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.robots = ""
        self.canonical = ""
        self.headings: list[Heading] = []
        self.links: list[str] = []
        self.images_total = 0
        self.images_missing_alt = 0
        self.json_ld_raw: list[str] = []
        self.text_parts: list[str] = []
        self._capture: str | None = None  # 'title' | 'h1'..'h6' | 'jsonld'
        self._buffer: list[str] = []
        self._skip_depth = 0  # inside <script>/<style>: text is not body copy

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            if tag == "script" and a.get("type", "").lower() == "application/ld+json":
                self._capture, self._buffer = "jsonld", []
            self._skip_depth += 1
            return
        if tag == "title":
            self._capture, self._buffer = "title", []
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description" and not self.meta_description:
                self.meta_description = a.get("content", "").strip()
            elif name == "robots" and not self.robots:
                self.robots = a.get("content", "").strip()
        elif tag == "link":
            # rel is a space-separated token list.
            if "canonical" in a.get("rel", "").lower().split() and not self.canonical:
                self.canonical = a.get("href", "").strip()
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._capture, self._buffer = tag, []
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                self.links.append(href)
        elif tag == "img":
            self.images_total += 1
            # A MISSING alt and an EMPTY alt are different: alt="" is the valid,
            # deliberate marker for a decorative image, so it is NOT a finding.
            if "alt" not in a:
                self.images_missing_alt += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            if self._capture == "jsonld":
                self.json_ld_raw.append("".join(self._buffer).strip())
                self._capture, self._buffer = None, []
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._capture is None or tag != self._capture:
            return
        text = _WS_RE.sub(" ", "".join(self._buffer)).strip()
        if tag == "title":
            if not self.title:
                self.title = text
        else:
            self.headings.append(Heading(level=int(tag[1]), text=text))
        self._capture, self._buffer = None, []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)
        if self._skip_depth == 0:
            self.text_parts.append(data)


def _same_host(page_url: str, href: str) -> bool:
    """Whether ``href`` stays on ``page_url``'s host. A relative href is internal by
    definition; a scheme we cannot compare (mailto:, tel:, #anchor) is neither."""
    parts = urlsplit(href)
    if parts.scheme and parts.scheme not in ("http", "https"):
        return False
    if not parts.netloc:
        return bool(parts.path) and not href.startswith("#")
    return parts.netloc.lower() == urlsplit(page_url).netloc.lower()


def normalize_url(url: str) -> str:
    """Canonical-comparison form: lowercase scheme+host, no fragment, no trailing
    slash. Used ONLY to compare a canonical against the analysed URL - two spellings
    of the same page must not read as a conflict."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


def parse_page(html: str, page_url: str = "") -> ParsedPage:
    """Parse fetched HTML into the descriptive :class:`ParsedPage`. Never raises: a
    malformed document yields whatever was harvestable (the detectors then report
    honestly on what IS there), because a broken page is exactly the kind we most
    need to report on rather than skip."""
    parser = _PageHtmlParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # a malformed document must degrade to a partial parse, never fail
        pass
    internal: list[str] = []
    external: list[str] = []
    for href in parser.links:
        if href.startswith("#") or urlsplit(href).scheme in ("mailto", "tel", "javascript"):
            continue
        (internal if _same_host(page_url, href) else external).append(href)
    return ParsedPage(
        url=page_url,
        title=parser.title,
        meta_description=parser.meta_description,
        robots=parser.robots,
        canonical=parser.canonical,
        headings=list(parser.headings),
        internal_links=internal,
        external_links=external,
        images_total=parser.images_total,
        images_missing_alt=parser.images_missing_alt,
        json_ld_raw=list(parser.json_ld_raw),
        body_text=_WS_RE.sub(" ", "".join(parser.text_parts)).strip(),
    )


# --------------------------------------------------------------------------- #
# The recommendation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Recommendation:
    """One detected issue + the fix we propose for it (JSON-serializable).

    ``current_value`` is the live value AS WE SAW IT. It is the drift-guard's
    reference and the revert's payload, so it is captured at detection time and
    never recomputed later. ``None`` = there was nothing there (a missing tag).
    """

    issue: str
    issue_code: str
    impact: str
    fix_kind: str
    fix_payload: dict[str, Any] = field(default_factory=dict)
    current_value: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def priority_score(self) -> float:
        return priority_score(self.impact, self.fix_kind)

    @property
    def quick_win(self) -> bool:
        return quick_win(self.impact, self.fix_kind)


def priority_score(impact: str, fix_kind: str) -> float:
    """Impact x Effort -> a 0-100 "do this first" ranking (bigger = sooner).

    ``impact / (impact + effort)`` rather than a raw product: it keeps the scale
    bounded, and it encodes the actual trade-off - a High-impact fix that takes a
    human a day (75 -> 43) should NOT outrank a Med-impact one-field edit (67).
    """
    weight = _IMPACT_WEIGHT.get(impact, 1.0)
    effort = _EFFORT.get(fix_kind, _EFFORT[MANUAL_FIX_KIND])
    return round(100.0 * weight / (weight + effort), 2)


def quick_win(impact: str, fix_kind: str) -> bool:
    """A quick win = worth doing AND applicable in one click.

    Deliberately narrower than "auto-applicable" (which is just ``fix_kind !=
    manual``): a Low-impact tweak is applicable but nobody should be told it is a
    win, and a heading/content rewrite is a win but never *quick*.
    """
    return fix_kind in _LOW_EFFORT_KINDS and impact != "Low"


def _rec(
    issue_code: str,
    issue: str,
    *,
    current: str | None = None,
    proposed: str | None = None,
    detail: dict[str, Any] | None = None,
    impact: str | None = None,
    fix_kind: str | None = None,
) -> Recommendation:
    """Build a recommendation, defaulting impact + fix kind from the taxonomy."""
    kind = fix_kind or _ISSUE_FIX_KIND.get(issue_code, MANUAL_FIX_KIND)
    payload: dict[str, Any] = {}
    if proposed is not None:
        payload["proposed_value"] = proposed
    return Recommendation(
        issue=issue,
        issue_code=issue_code,
        impact=impact or _ISSUE_IMPACT.get(issue_code, "Low"),
        fix_kind=kind,
        fix_payload=payload,
        current_value=current,
        detail=detail or {},
    )


# --------------------------------------------------------------------------- #
# Fix proposals (deterministic; no LLM, so they work with zero keys)
# --------------------------------------------------------------------------- #
def _truncate_words(text: str, limit: int) -> str:
    """Trim to ``limit`` chars on a WORD boundary (never mid-word)."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" -|,:;")
    return cut or text[:limit].rstrip()


def propose_title(current: str, keyword: str, brand: str) -> str:
    """A deterministic title inside the 30-60 band: keyword front-loaded, brand
    suffixed if it fits. Deliberately mechanical - a lead reviews every proposal
    before it goes live, and a keyless install must still get a usable suggestion."""
    base = current.strip() or keyword.strip() or "Untitled"
    if keyword and keyword.lower() not in base.lower():
        base = f"{keyword.strip()} | {base}" if base != keyword.strip() else keyword.strip()
    suffix = f" | {brand.strip()}" if brand and brand.strip().lower() not in base.lower() else ""
    if len(base) + len(suffix) > TITLE_MAX_CHARS:
        base = _truncate_words(base, TITLE_MAX_CHARS - len(suffix))
    return f"{base}{suffix}"[:TITLE_MAX_CHARS]


def propose_meta(current: str, keyword: str, body_text: str) -> str:
    """A deterministic meta description inside the 120-160 band, seeded from the
    existing meta (or the page's opening prose) with the keyword ensured present."""
    seed = current.strip() or body_text.strip()[: META_MAX_CHARS * 2]
    if keyword and keyword.lower() not in seed.lower():
        seed = f"{keyword.strip()}: {seed}" if seed else keyword.strip()
    return _truncate_words(seed, META_MAX_CHARS)


# --------------------------------------------------------------------------- #
# The detectors (pure; one recommendation per detected issue)
# --------------------------------------------------------------------------- #
def detect_title(page: ParsedPage, keyword: str, brand: str) -> list[Recommendation]:
    """Title findings. Boundaries are INCLUSIVE: exactly 30 or exactly 60 chars is
    inside the band and raises nothing."""
    title = page.title.strip()
    if not title:
        return [
            _rec(
                "title_missing",
                "Page has no title tag",
                current=None,
                proposed=propose_title("", keyword, brand),
                detail={"length": 0, "min": TITLE_MIN_CHARS, "max": TITLE_MAX_CHARS},
            )
        ]
    out: list[Recommendation] = []
    length = len(title)
    if length < TITLE_MIN_CHARS:
        out.append(
            _rec(
                "title_short",
                f"Title is {length} characters - under the {TITLE_MIN_CHARS}-character minimum",
                current=title,
                proposed=propose_title(title, keyword, brand),
                detail={"length": length, "min": TITLE_MIN_CHARS, "min_pixels": TITLE_MIN_PIXELS},
            )
        )
    elif length > TITLE_MAX_CHARS:
        out.append(
            _rec(
                "title_long",
                f"Title is {length} characters - over the {TITLE_MAX_CHARS}-character limit "
                "and will be truncated in search results",
                current=title,
                proposed=_truncate_words(title, TITLE_MAX_CHARS),
                detail={"length": length, "max": TITLE_MAX_CHARS, "max_pixels": TITLE_MAX_PIXELS},
            )
        )
    if keyword and keyword.lower() not in title.lower():
        out.append(
            _rec(
                "title_keyword_missing",
                f"Title does not contain the target keyword '{keyword}'",
                current=title,
                proposed=propose_title(title, keyword, brand),
                detail={"keyword": keyword},
            )
        )
    if brand and brand.lower() not in title.lower():
        out.append(
            _rec(
                "title_no_brand",
                f"Title does not carry the brand name '{brand}'",
                current=title,
                proposed=propose_title(title, keyword, brand),
                detail={"brand": brand},
            )
        )
    return out


def detect_meta(
    page: ParsedPage, keyword: str, *, duplicate_of: str | None = None
) -> list[Recommendation]:
    """Meta-description findings. ``duplicate_of`` comes from an audit run (a single
    page fetch cannot know another page shares its description)."""
    meta = page.meta_description.strip()
    if not meta:
        return [
            _rec(
                "meta_missing",
                "Page has no meta description",
                current=None,
                proposed=propose_meta("", keyword, page.body_text),
                detail={"length": 0, "min": META_MIN_CHARS, "max": META_MAX_CHARS},
            )
        ]
    out: list[Recommendation] = []
    length = len(meta)
    if length < META_MIN_CHARS:
        out.append(
            _rec(
                "meta_short",
                f"Meta description is {length} characters - under the {META_MIN_CHARS}-character minimum",
                current=meta,
                proposed=propose_meta(meta, keyword, page.body_text),
                detail={"length": length, "min": META_MIN_CHARS},
            )
        )
    elif length > META_MAX_CHARS:
        out.append(
            _rec(
                "meta_long",
                f"Meta description is {length} characters - over the {META_MAX_CHARS}-character "
                "limit and will be truncated in search results",
                current=meta,
                proposed=_truncate_words(meta, META_MAX_CHARS),
                detail={"length": length, "max": META_MAX_CHARS},
            )
        )
    if duplicate_of:
        out.append(
            _rec(
                "meta_duplicate",
                f"Meta description duplicates {duplicate_of}",
                current=meta,
                proposed=propose_meta("", keyword, page.body_text),
                detail={"duplicate_of": duplicate_of},
            )
        )
    return out


def detect_headings(page: ParsedPage, keyword: str) -> list[Recommendation]:
    """Heading findings: the H1 contract + a non-skipping hierarchy."""
    out: list[Recommendation] = []
    h1s = page.h1s
    if not h1s:
        out.append(
            _rec(
                "h1_missing",
                "Page has no H1 heading",
                current=None,
                proposed=(keyword or page.title).strip() or None,
                detail={"h1_count": 0, "expected": H1_EXPECTED_COUNT},
            )
        )
    elif len(h1s) > H1_EXPECTED_COUNT:
        out.append(
            _rec(
                "h1_multiple",
                f"Page has {len(h1s)} H1 headings - exactly {H1_EXPECTED_COUNT} is expected",
                current=h1s[0].text,
                proposed=h1s[0].text,
                detail={"h1_count": len(h1s), "expected": H1_EXPECTED_COUNT,
                        "h1s": [h.text for h in h1s]},
            )
        )
    if h1s and keyword and keyword.lower() not in h1s[0].text.lower():
        out.append(
            _rec(
                "h1_keyword_missing",
                f"H1 does not contain the target keyword '{keyword}'",
                current=h1s[0].text,
                proposed=f"{keyword.strip()} - {h1s[0].text}" if h1s[0].text else keyword.strip(),
                detail={"keyword": keyword, "h1": h1s[0].text},
            )
        )
    skip = _first_hierarchy_skip(page.headings)
    if skip is not None:
        prev, nxt = skip
        out.append(
            _rec(
                "heading_hierarchy_skip",
                f"Heading hierarchy skips from H{prev} to H{nxt}",
                current=f"H{prev} -> H{nxt}",
                detail={"from": prev, "to": nxt},
            )
        )
    return out


def _first_hierarchy_skip(headings: list[Heading]) -> tuple[int, int] | None:
    """The first place the outline jumps DOWN more than one level (H2 -> H4). Going
    back up any number of levels is legal, so only descents are checked."""
    previous: int | None = None
    for heading in headings:
        if previous is not None and heading.level > previous + 1:
            return (previous, heading.level)
        previous = heading.level
    return None


def detect_content(
    page: ParsedPage, keyword: str, *, duplicate_of: str | None = None
) -> list[Recommendation]:
    """Body findings: length, keyword density, readability, duplication."""
    out: list[Recommendation] = []
    words = page.word_count
    if words < THIN_CONTENT_MIN_WORDS:
        out.append(
            _rec(
                "thin_content",
                f"Page has {words} words - under the {THIN_CONTENT_MIN_WORDS}-word "
                "depth floor for a competitive page",
                detail={"words": words, "min": THIN_CONTENT_MIN_WORDS},
            )
        )
    if keyword and words:
        density = keyword_density(page.body_text, keyword)
        if density > PRIMARY_DENSITY_HARD_CEILING:
            out.append(
                _rec(
                    "keyword_density_high",
                    f"Keyword density is {density:.1%} - over the "
                    f"{PRIMARY_DENSITY_HARD_CEILING:.0%} stuffing ceiling",
                    detail={"density": round(density, 4),
                            "ceiling": PRIMARY_DENSITY_HARD_CEILING},
                )
            )
        elif density < PRIMARY_DENSITY_TARGET_MIN:
            out.append(
                _rec(
                    "keyword_density_low",
                    f"Keyword density is {density:.1%} - under the "
                    f"{PRIMARY_DENSITY_TARGET_MIN:.1%} target",
                    detail={"density": round(density, 4),
                            "target_min": PRIMARY_DENSITY_TARGET_MIN},
                )
            )
    if words:
        flesch = flesch_reading_ease(page.body_text)
        if flesch < READABILITY_MIN_FLESCH:
            out.append(
                _rec(
                    "readability_low",
                    f"Reading ease is {flesch:.0f} - below the {READABILITY_MIN_FLESCH:.0f} "
                    "floor for a general audience",
                    detail={"flesch": round(flesch, 1), "min": READABILITY_MIN_FLESCH},
                )
            )
    if duplicate_of:
        out.append(
            _rec(
                "duplicate_content",
                f"Page content duplicates {duplicate_of}",
                detail={"duplicate_of": duplicate_of},
            )
        )
    return out


def keyword_density(body_text: str, keyword: str) -> float:
    """The share of the body the keyword occupies, counted as PHRASE occurrences x
    phrase length / total words - the same measure ``content_generator`` reports and
    ``content_qa`` bands, so a live page and a drafted one are judged identically."""
    words = _WORD_RE.findall(body_text.lower())
    if not words:
        return 0.0
    terms = _WORD_RE.findall(keyword.lower())
    if not terms:
        return 0.0
    hits = sum(
        1 for i in range(len(words) - len(terms) + 1) if words[i : i + len(terms)] == terms
    )
    return (hits * len(terms)) / len(words)


def detect_schema(page: ParsedPage) -> list[Recommendation]:
    """JSON-LD findings: present at all, and parseable when present."""
    if not page.json_ld_raw:
        return [
            _rec(
                "schema_missing",
                "Page carries no JSON-LD structured data",
                detail={"blocks": 0},
            )
        ]
    for raw in page.json_ld_raw:
        try:
            json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return [
                _rec(
                    "schema_invalid",
                    "Page has a JSON-LD block that is not valid JSON",
                    detail={"blocks": len(page.json_ld_raw)},
                )
            ]
    return []


def detect_links(page: ParsedPage, *, orphan: bool = False) -> list[Recommendation]:
    """Internal-linking findings. ``orphan`` (nothing links TO this page) needs the
    site graph, so it only ever arrives from an audit run."""
    out: list[Recommendation] = []
    expected = expected_internal_links(page.word_count)
    found = len(page.internal_links)
    if found < expected:
        out.append(
            _rec(
                "internal_links_few",
                f"Page has {found} internal links - at least {expected} expected for "
                f"{page.word_count} words",
                detail={"found": found, "expected": expected, "words": page.word_count,
                        "per_1000_words": INTERNAL_LINKS_PER_1000_WORDS},
            )
        )
    if orphan:
        out.append(
            _rec(
                "internal_link_orphan",
                "No internal links point to this page - it is orphaned",
                detail={"inbound_internal_links": 0},
            )
        )
    return out


def expected_internal_links(word_count: int) -> int:
    """>= 2 per ~1000 words, and at least 1 on any page with prose at all: a page
    with 200 words still must not be a dead end."""
    if word_count <= 0:
        return 0
    return max(1, math.ceil(INTERNAL_LINKS_PER_1000_WORDS * word_count / 1000.0))


def detect_images(page: ParsedPage) -> list[Recommendation]:
    """Image findings. ``alt=""`` is the CORRECT markup for a decorative image, so
    only a MISSING alt attribute is a finding (the parser keeps them apart)."""
    if page.images_missing_alt <= 0:
        return []
    return [
        _rec(
            "image_alt_missing",
            f"{page.images_missing_alt} of {page.images_total} images have no alt attribute",
            detail={"missing": page.images_missing_alt, "total": page.images_total},
        )
    ]


def detect_canonical(page: ParsedPage) -> list[Recommendation]:
    """Canonical findings: present, and pointing at THIS page."""
    canonical = page.canonical.strip()
    if not canonical:
        return [
            _rec("canonical_missing", "Page has no canonical link", current=None,
                 proposed=page.url or None, detail={})
        ]
    if page.url and normalize_url(canonical) != normalize_url(page.url):
        return [
            _rec(
                "canonical_conflict",
                f"Canonical points to a different URL ({canonical})",
                current=canonical,
                proposed=page.url,
                detail={"canonical": canonical, "page_url": page.url},
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# The content score (the content_qa rubric, applied to a LIVE page)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContentScore:
    """The 0-100 content score + the sub-scores it is made of.

    ``degraded`` is TRUE when a sub-score had to be OMITTED for want of a provider
    key (entity coverage needs a SERP teardown). The total is then re-weighted over
    what WAS measurable and ``notes`` says so - an honest partial score, never a
    silently-invented one.
    """

    total: float
    sub_scores: dict[str, float]
    degraded: bool
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "sub_scores": self.sub_scores,
            "degraded": self.degraded,
            "notes": self.notes,
        }


# The content score's weight vector. Mirrors the shape of content_qa's
# DIMENSION_WEIGHTS (renormalised over the four dimensions a live-page fetch can
# actually measure); a dimension we cannot measure is dropped and the rest
# renormalise, rather than being scored 0 (which would be a lie about the page).
_SCORE_WEIGHTS: dict[str, float] = {
    "entity_coverage": 0.30,
    "keyword_handling": 0.25,
    "structure_readability": 0.25,
    "depth": 0.20,
}


def _band(value: float, bands: list[tuple[float, float, float]], default: float) -> float:
    """The first band ``(low, high, score)`` that contains ``value``, else ``default``."""
    for low, high, score in bands:
        if low <= value <= high:
            return score
    return default


def score_page_content(
    page: ParsedPage, keyword: str, *, entities: list[str] | None = None
) -> ContentScore:
    """Score a live page against its target keyword, REUSING the content_qa rubric.

    ``entities`` are the table-stakes entities a SERP teardown found the ranking pages
    all cover. With no Serper key there is no teardown, so ``entities`` is ``None``,
    the entity_coverage dimension is OMITTED, and the score renormalises over the
    three deterministic dimensions with ``degraded=True``. Never raises.
    """
    subs: dict[str, float] = {}
    notes: list[str] = []
    degraded = False

    # 1. Entity coverage - content_qa's _covered_entities, verbatim (§11.5).
    if entities:
        covered, missing = _covered_entities(page.body_text, entities)
        subs["entity_coverage"] = round(100.0 * len(covered) / len(entities), 1)
        if missing:
            notes.append(f"missing table-stakes entities: {', '.join(missing[:10])}")
    else:
        degraded = True
        notes.append(
            "entity coverage omitted: no SERP teardown available (Serper key absent) - "
            "scored on the deterministic dimensions only"
        )

    # 2. Keyword handling - the content_generator density bands content_qa uses.
    if keyword:
        density = keyword_density(page.body_text, keyword)
        if density > PRIMARY_DENSITY_HARD_CEILING:
            subs["keyword_handling"] = 25.0
            notes.append(f"keyword density {density:.3f} over the stuffing ceiling")
        elif density > PRIMARY_DENSITY_TARGET_MAX:
            subs["keyword_handling"] = 72.0
        elif density < PRIMARY_DENSITY_TARGET_MIN:
            subs["keyword_handling"] = 68.0
        else:
            subs["keyword_handling"] = 100.0
        if keyword.lower() not in page.title.lower():
            subs["keyword_handling"] = max(0.0, subs["keyword_handling"] - 10.0)
            notes.append("primary not front-loaded in the title")
    else:
        degraded = True
        notes.append("keyword handling omitted: the analysis carries no target keyword")

    # 3. Structure + readability - content_qa's H1 contract + Flesch bands (§11.8/11.11).
    structure = 100.0
    if len(page.h1s) != H1_EXPECTED_COUNT:
        structure -= 30.0
    if _first_hierarchy_skip(page.headings) is not None:
        structure -= 15.0
    flesch = flesch_reading_ease(page.body_text) if page.body_text else 0.0
    readability = _band(
        flesch, [(55.0, 75.0, 100.0), (45.0, 85.0, 85.0), (35.0, 95.0, 70.0)], 50.0
    )
    subs["structure_readability"] = round(max(0.0, (structure + readability) / 2.0), 1)

    # 4. Depth - the thin-content floor, scaled (a page at the floor scores 100).
    words = page.word_count
    subs["depth"] = round(min(100.0, 100.0 * words / THIN_CONTENT_MIN_WORDS), 1)

    total_weight = sum(_SCORE_WEIGHTS[k] for k in subs)
    total = (
        round(sum(subs[k] * _SCORE_WEIGHTS[k] for k in subs) / total_weight, 1)
        if total_weight
        else 0.0
    )
    return ContentScore(total=total, sub_scores=subs, degraded=degraded, notes=notes)


# --------------------------------------------------------------------------- #
# The two analysis paths
# --------------------------------------------------------------------------- #
def analyze_parsed_page(
    page: ParsedPage,
    keyword: str,
    *,
    brand: str = "",
    entities: list[str] | None = None,
) -> tuple[list[Recommendation], ContentScore]:
    """Run every deterministic detector over a parsed page + score its content.

    Pure + deterministic: same page + keyword -> same recommendations, in the same
    order. This is the path taken when NO audit run backs the analysis.
    """
    score = score_page_content(page, keyword, entities=entities)
    recs: list[Recommendation] = [
        *detect_title(page, keyword, brand),
        *detect_meta(page, keyword),
        *detect_headings(page, keyword),
        *detect_content(page, keyword),
        *detect_schema(page),
        *detect_links(page),
        *detect_images(page),
        *detect_canonical(page),
    ]
    if score.total < CONTENT_SCORE_FLOOR:
        recs.append(
            _rec(
                "content_score_low",
                f"Content scores {score.total:.0f}/100 against '{keyword or 'the page topic'}' "
                f"- below the {CONTENT_SCORE_FLOOR:.0f} floor",
                detail=score.as_dict(),
            )
        )
    return recs, score


def map_audit_findings(findings: list[dict[str, Any]], page_url: str) -> list[Recommendation]:
    """Map an audit run's on-page findings onto our taxonomy - never re-detect them.

    Where a 363-check run exists it already crawled the page WITH the SERP, the site
    graph and GSC in hand; a single-page fetch cannot match that, so the engine's
    verdict wins. Only failing/warning checks with an unambiguous mapping become
    recommendations, and impact comes from the engine's own severity
    (critical|major -> High, minor -> Med, info -> Low).

    Findings for OTHER pages are skipped: an analysis is about ONE URL.
    """
    out: list[Recommendation] = []
    seen: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("status", "")).lower() not in _ACTIONABLE_STATUSES:
            continue
        issue_code = _CHECK_ISSUE.get(str(finding.get("check_id", "")).upper())
        if issue_code is None or issue_code in seen:
            continue
        found_url = str(finding.get("page_url") or finding.get("url") or "")
        if found_url and page_url and normalize_url(found_url) != normalize_url(page_url):
            continue
        seen.add(issue_code)
        impact = _SEVERITY_IMPACT.get(str(finding.get("severity", "")).lower(), "Low")
        name = str(finding.get("check_name") or issue_code.replace("_", " "))
        remediation = str(finding.get("remediation") or "")
        out.append(
            _rec(
                issue_code,
                remediation.strip() or name,
                impact=impact,
                detail={
                    "source": "audit",
                    "check_id": finding.get("check_id"),
                    "check_name": name,
                    "severity": finding.get("severity"),
                    "evidence": finding.get("evidence_json"),
                },
            )
        )
    return out


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts on_page EXTRA shape).
# --------------------------------------------------------------------------- #
_IMPACT_TONE: dict[str, str] = {"High": "crit", "Med": "warn", "Low": "info"}
_STATUS_TONE: dict[str, str] = {
    "open": "warn",       # something still to do
    "applied": "ok",      # live on the site
    "held": "warn",       # we could not write it - still outstanding
    "dismissed": "mut",   # deliberately not doing it
    "reverted": "mut",    # rolled back
}
_STATUS_LABEL: dict[str, str] = {
    "open": "Open", "applied": "Applied", "held": "Held",
    "dismissed": "Dismissed", "reverted": "Reverted",
}


def _rec_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Page, Issue, Impact, Status] with tones."""
    impact = str(row.get("impact") or "Low")
    status = str(row.get("status") or "open")
    return [
        str(row.get("page_url", "") or ""),
        str(row.get("issue", "") or ""),
        ToolCellObj(v=impact, tone=cast("Any", _IMPACT_TONE.get(impact, "info"))),
        ToolCellObj(
            v=_STATUS_LABEL.get(status, status.title()),
            tone=cast("Any", _STATUS_TONE.get(status, "mut")),
        ),
    ]


def build_workspace(stats: OnPageStats, recommendations: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the on-page tool workspace (KPIs + the recommendation table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Page", "Issue", "Impact", "Status"]`` (the tool-workspace
    contract test enforces byte-identity)."""
    kpis = [
        ToolKpi(label="Pages analyzed", value=f"{stats.analyzed:,}"),
        ToolKpi(label="Open suggestions", value=f"{stats.open:,}"),
        ToolKpi(label="Applied", value=f"{stats.applied:,}"),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_rec_row(r) for r in recommendations[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
