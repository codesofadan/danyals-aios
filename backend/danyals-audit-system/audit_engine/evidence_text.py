"""Turn a check's evidence into a sentence a client can read.

Evidence is engineering data - a dict of whatever the analyzer measured - and it
was being printed verbatim into the client PDF, the client workbook and the
client sheets. Real output that shipped to a client included::

    Observed: inputs_declared: 24, verdicts_counted: 93, status_breakdown:
    {'fail': 34, 'warn': 36, 'pass': 23, 'n_a': 3}.

    cache_control: not captured

    scorers.aggregator

The first is a Python dict repr. The second says the opposite of the remediation
printed directly beneath it. The third is an internal module path, in a column
headed "Evidence".

This module is the one place that decides what a client sees, and the rule it
enforces is: **say something true and useful, or say nothing.** An empty string
is a correct answer; every caller must treat it as "omit the clause" rather than
"print an empty sentence".

Three shapes are refused outright, because each is a leak rather than a
measurement: a nested dict (internal structure), a dotted module path
(implementation detail), and a bare boolean with no phrasing (``covers_host:
False`` tells a client nothing). ``None`` is DROPPED rather than rendered as
"not captured" - a value we did not record is not a finding about the site, and
printing it as one produced cards that contradicted their own remediation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: Keys that exist for the engine's benefit, never the client's. Provenance,
#: thresholds, method notes and operator instructions belong in the workbook's
#: diagnostic sheets, not in a sentence under a client-facing finding.
INTERNAL_KEYS: frozenset[str] = frozenset({
    "inputs_ran", "inputs_missing", "inputs_declared", "weighting",
    "status_breakdown", "verdicts_counted", "partial_rollup", "analyzer_error",
    "threshold_basis", "assessment_rule", "method", "operator_note",
    "audits_looked_for", "audit", "basis", "ranking_context", "context",
    "note", "crawl_was_partial", "crawl_coverage", "metrics_available",
    "reporting_floor_ms", "good_threshold", "poor_threshold",
    "good_threshold_ms", "poor_threshold_ms", "word_threshold",
    "warn_threshold_hops", "scoreDisplayMode", "score", "display", "items",
    "id", "title", "description", "numericValue", "treated_as_static",
    "audits_not_in_this_lighthouse", "opportunity", "failing", "problems",
    "examples", "example_sources", "san_count", "ip_count", "signals",
})

#: A dotted path, a repr, or an exception string - plainly code, never a finding.
_CODE_LIKE = re.compile(r"^[a-z_]+(\.[a-z_]+){2,}$|^<.+>$|^[A-Za-z]+Error\b")

#: Booleans are rendered only where we can say what True and False MEAN. A bare
#: ``has_etag: False`` is noise; "sends no ETag" is a finding. A key absent from
#: this map is dropped rather than guessed at.
BOOL_PHRASING: dict[str, tuple[str, str]] = {
    "has_charset": ("declares a character set", "declares no character set"),
    "nosniff": ("sends X-Content-Type-Options", "does not send X-Content-Type-Options"),
    "has_etag": ("sends an ETag", "sends no ETag"),
    "has_last_modified": ("sends Last-Modified", "sends no Last-Modified"),
    "covers_host": ("the certificate covers this domain",
                    "the certificate does NOT cover this domain"),
    "advertises_h3": ("advertises HTTP/3", "does not advertise HTTP/3"),
    "has_schema": ("carries structured data", "carries no structured data"),
    "breadcrumb_schema": ("has BreadcrumbList markup", "has no BreadcrumbList markup"),
    "breadcrumb_nav_present": ("shows a breadcrumb trail", "shows no breadcrumb trail"),
    "image_sitemap_present": ("has an image sitemap", "has no image sitemap"),
    "video_sitemap_present": ("has a video sitemap", "has no video sitemap"),
    "has_amp": ("uses AMP", "does not use AMP"),
    "noindex": ("is set to noindex", "is indexable"),
    "nofollow": ("is set to nofollow", "passes link signal"),
    "has_h1": ("has an H1 heading", "has no H1 heading"),
    "has_title": ("has a title tag", "has no title tag"),
    "served_from_cache": ("was served from cache", "was served from the origin"),
    "present": ("is present", "is absent"),
}

#: Key -> the words a client would use for it. Anything not listed falls back to
#: the key with underscores replaced, which reads acceptably for most.
LABELS: dict[str, str] = {
    "response_ms": "server response",
    "lcp_ms": "largest contentful paint",
    "inp_ms": "interaction to next paint",
    "cls": "layout shift score",
    "total_blocking_time_ms": "main-thread blocking",
    "estimated_savings_ms": "estimated saving",
    "estimated_savings_bytes": "wasted bytes",
    "total_estimated_savings_ms": "total estimated saving",
    "bytes": "page weight",
    "word_count": "words",
    "content_encoding": "compression",
    "cache_control": "cache policy",
    "max_age_seconds": "cache lifetime",
    "http_version": "protocol",
    "hsts_max_age": "HSTS lifetime",
    "days_until_expiry": "days until the certificate expires",
    "tls_version": "TLS version",
    "content_type": "content type",
    "x_robots_tag": "X-Robots-Tag header",
    "meta_robots": "robots meta tag",
    "header_canonical": "canonical in the response header",
    "html_canonical": "canonical in the page",
    "pages_crawled": "pages crawled",
    "pages_measured": "pages measured",
    "not_found_count": "pages returning 404",
    "linked_not_found_count": "broken links from other pages",
    "server_error_count": "pages returning a server error",
    "soft_404_count": "pages that say not found but return 200",
    "redirect_loop_count": "redirect loops",
    "multi_hop_count": "multi-hop redirects",
    "long_chain_count": "long redirect chains",
    "temporary_redirect_count": "temporary redirects",
    "orphan_count": "pages with no internal links",
    "duplicate_groups": "groups of duplicate pages",
    "pages_in_a_duplicate_group": "duplicate pages",
    "faceted_urls": "filter and sort URLs",
    "indexable_search_urls": "indexable search pages",
    "thin_pages": "pages under the content threshold",
    "images_seen": "images",
    "without_alt": "images with no alt text",
    "blocked_by_robots": "images blocked by robots.txt",
    "http_resource_count": "resources loaded insecurely",
    "sitemap_urls": "URLs in the sitemap",
    "non_200": "sitemap URLs that do not return 200",
    "parse_errors": "sitemaps that failed to parse",
    "noindex_in_sitemap": "noindexed URLs listed in the sitemap",
    "robots_blocked_in_sitemap": "robots-blocked URLs in the sitemap",
    "opportunity_count": "improvement opportunities",
    "performance_score": "performance score",
    "failing_count": "failing checks",
    "incomplete_count": "incomplete schema blocks",
    "missing_required": "missing required properties",
    "cdn_detected": "content delivery network",
    "reverse_dns": "hosting provider",
    "server": "web server",
    "deeper_than_3_clicks": "pages more than three clicks from the homepage",
    "unreachable_from_homepage": "pages not reachable from the homepage",
    "internal_links": "internal links",
    "avg_inbound": "average inbound links per page",
    "pages_with_no_inbound": "pages with no inbound links",
    "pages_with_video": "pages with video",
    "linked_pairs_compared": "internal links examined",
    "topically_related": "links between related pages",
    "semantic_tags_present": "semantic landmarks",
    "types": "schema types",
    "block_count": "schema blocks",
    "final_url_scheme": "protocol",
    "share_thin": "share of pages under the threshold",
    "related_share": "share of links between related pages",
    "top_decile_share": "share of links pointing at the top 10% of pages",
    "text_to_html_ratio": "text-to-HTML ratio",
    "question_ratio": "share of headings phrased as questions",
    "first_paragraph_words": "words in the opening paragraph",
    "avg_sentence_words": "average sentence length",
    "long_sentence_share": "share of very long sentences",
    "heading_count": "headings",
    "question_headings": "question-style headings",
    "h2_count": "H2 headings",
    "table_count": "tables",
    "passage_count": "well-sized passages",
    "sentence_count": "sentences",
    "intro_words": "words in the intro",
    "generic_anchors": "generic link labels",
    "footer_links": "footer links",
    "external_links": "outbound links",
    "schema_count": "schema blocks",
    "unique_types": "schema types",
    "lighthouse_score": "score",
    "category": "category",
}

#: Keys whose numeric value is a duration in milliseconds.
_MS = ("_ms", "_seconds")
#: Keys whose numeric value is a share, rendered as a percentage.
_SHARE = ("_share", "_ratio", "_pct", "share_", "_rate")

MAX_LEN = 240


def _fmt_number(key: str, value: float) -> str:
    lower = key.lower()
    if any(lower.endswith(s) or lower.startswith(s) for s in _SHARE) and 0 <= value <= 1:
        return f"{value:.0%}"
    if lower.endswith(_MS):
        # Past a second, seconds read better than four digits of milliseconds.
        if lower.endswith("_ms") and value >= 1000:
            return f"{value / 1000:.1f}s"
        unit = "ms" if lower.endswith("_ms") else "s"
        return f"{value:,.0f}{unit}"
    if lower.endswith("_bytes") or lower == "bytes":
        for unit in ("bytes", "KB", "MB"):
            if value < 1024 or unit == "MB":
                return f"{value:,.0f} {unit}" if unit == "bytes" else f"{value:,.1f} {unit}"
            value /= 1024
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{int(value):,}"


def _render(key: str, value: Any) -> str | None:
    """One evidence pair as a phrase, or None to drop it."""
    if key in INTERNAL_KEYS or key.startswith("_"):
        return None
    if value is None or value == "":
        # A value we did not record is not a finding about the site.
        return None
    if isinstance(value, Mapping):
        return None  # internal structure, never a client-facing fact
    if isinstance(value, bool):
        phrasing = BOOL_PHRASING.get(key)
        if not phrasing:
            return None
        text = phrasing[0] if value else phrasing[1]
        return text or None
    label = LABELS.get(key, key.replace("_", " "))
    if isinstance(value, (int, float)):
        # A colon separates the label from the number. Without it "words in the
        # opening paragraph 2" reads as a garbled phrase rather than a reading.
        return f"{label}: {_fmt_number(key, float(value))}"
    if isinstance(value, (list, tuple, set)):
        items = [str(v) for v in value if v is not None and not isinstance(v, (Mapping, list))]
        if not items:
            return None
        if len(items) <= 3 and all(len(i) <= 40 and not _CODE_LIKE.match(i) for i in items):
            return f"{label}: {', '.join(items)}"
        return f"{len(items)} {label}"
    text = str(value).strip()
    if not text or _CODE_LIKE.match(text) or len(text) > 120:
        return None
    # An agent-written value is often already a sentence. Prefixing it with its
    # key produces "hidden content or cloaking None detected. All pages render
    # transparently...", which reads as broken English.
    if text[:1].isupper() and text.rstrip().endswith((".", "!")):
        return text
    return f"{label} {text}"


def humanise_evidence(evidence: Any, *, limit: int = 3) -> str:
    """A short, client-safe phrase describing what was measured.

    Returns "" when nothing in the evidence is worth showing a client. Callers
    MUST treat that as "omit the clause" - printing an empty observation is how
    "Observed: ." reached a report.
    """
    if isinstance(evidence, str):
        text = evidence.strip()
        return "" if _CODE_LIKE.match(text) else text[:MAX_LEN]
    if not isinstance(evidence, Mapping) or not evidence:
        return ""

    # A written `reason` is already a sentence someone chose. Prefer it, unless
    # it is an exception string or an operator instruction.
    reason = evidence.get("reason")
    if isinstance(reason, str) and reason.strip() and not _CODE_LIKE.match(reason.strip()):
        return reason.strip()[:MAX_LEN]

    parts: list[str] = []
    for key, value in evidence.items():
        rendered = _render(key, value)
        if rendered:
            parts.append(rendered)
        if len(parts) >= limit:
            break
    return ("; ".join(parts))[:MAX_LEN]


#: Suffixes that make a dotted token a HOSTNAME rather than an import path. A
#: URL is legitimate evidence - "canonical https://www.example.com" is exactly
#: what a client needs to see - so the module-path guard must not fire on one.
_HOSTNAME_TAIL = re.compile(
    r"\.(com|net|org|io|co|uk|pk|dev|ai|app|xyz|info|biz|edu|gov|me|us|ca|au|"
    r"de|fr|nl|es|it|in|jp|cn|br|ru|se|no|fi|dk|pl|cz|gr|pt|tr|za|html?|php|"
    r"aspx?|jsp|js|css|json|xml|txt|pdf|png|jpe?g|webp|svg|gif|ico|woff2?)$",
    re.I,
)


def _looks_like_a_module_path(text: str) -> bool:
    """A dotted lowercase path that is code, not a host or a filename."""
    if "://" in text or "/" in text:
        return False
    for token in re.findall(r"\b[a-z_]+(?:\.[a-z_]+){2,}\b", text):
        if not _HOSTNAME_TAIL.search(token):
            return True
    return False


def evidence_is_client_safe(text: str) -> bool:
    """True when ``text`` contains none of the three shapes we refuse.

    Used by the guard test rather than at runtime: the renderer is meant to make
    this true by construction, and a test proving that is worth more than a
    check that quietly repairs bad output in production.
    """
    if "{" in text or "}" in text:
        return False
    if _looks_like_a_module_path(text):
        return False
    # `key: None` / `key=False` is a leaked repr. A sentence that happens to
    # begin "None detected" is English, and an AI-written finding may well say
    # exactly that - flagging it would make the guard fire on correct output.
    return not re.search(r"\b\w+\s*[:=]\s*(True|False|None)\b", text)
