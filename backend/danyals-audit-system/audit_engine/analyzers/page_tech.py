"""Per-page technical checks over data the crawler already parses.

Schema blocks, Open Graph, Twitter cards, canonical tags, mixed content and
semantic structure were all parsed and then thrown away, because no analyzer
read them. Every threshold here has a primary source where one exists, and is
marked JUDGEMENT where it does not.
"""

from __future__ import annotations

import re
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check

#: ogp.me, "The four required properties for every page".
OG_REQUIRED = ("og:title", "og:type", "og:image", "og:url")

#: developer.x.com/en/docs/twitter-for-websites/cards - summary_large_image
#: requires card, title and image; description is strongly recommended.
TWITTER_REQUIRED = ("twitter:card",)
TWITTER_RECOMMENDED = ("twitter:title", "twitter:description", "twitter:image")

#: schema.org types that Google documents as eligible for a rich result.
RICH_RESULT_TYPES = frozenset({
    "Article", "NewsArticle", "BlogPosting", "Product", "Recipe", "Event",
    "FAQPage", "HowTo", "JobPosting", "LocalBusiness", "Organization",
    "BreadcrumbList", "Review", "AggregateRating", "VideoObject", "Course",
    "SoftwareApplication", "Book", "Movie", "QAPage", "Dataset",
})

#: Properties Google documents as REQUIRED for the rich results people
#: actually want. Missing one makes the page ineligible, silently.
REQUIRED_PROPS: dict[str, tuple[str, ...]] = {
    "Article": ("headline",),
    "NewsArticle": ("headline",),
    "BlogPosting": ("headline",),
    "Product": ("name",),
    "Recipe": ("name", "recipeIngredient", "recipeInstructions"),
    "Event": ("name", "startDate", "location"),
    "FAQPage": ("mainEntity",),
    "HowTo": ("name", "step"),
    "JobPosting": ("title", "datePosted", "hiringOrganization"),
    "LocalBusiness": ("name", "address"),
    "BreadcrumbList": ("itemListElement",),
    "VideoObject": ("name", "thumbnailUrl", "uploadDate"),
}

_HTTP_RESOURCE = re.compile(
    r"""(?:src|href|action|data-src|poster)\s*=\s*["']\s*(http://[^"'\s>]+)""",
    re.IGNORECASE,
)
_SEMANTIC_TAGS = ("main", "header", "footer", "nav", "article", "section", "aside")


def _types(block: dict) -> list[str]:
    t = block.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def _all_types(p: Any) -> list[str]:
    out: list[str] = []
    for b in getattr(p, "schema_blocks", []) or []:
        if isinstance(b, dict):
            out.extend(_types(b))
    return out


# --------------------------------------------------------------------------
# Canonical
# --------------------------------------------------------------------------

@check("TECH-019", scope="page")
def check_canonical_tag(p: Any) -> Verdict:
    """TECH-019 - a self-referencing canonical.

    Without one, any URL variant of this page (parameters, trailing slash,
    upper case) competes with it, and Google picks the winner rather than you.
    """
    from audit_engine.analyzers.urls import normalise, same_page

    canonical = getattr(p, "canonical", None)
    url = getattr(p, "url", "") or ""
    ev = {"canonical": canonical, "url": url}
    if not canonical:
        return Verdict("fail", 3.0, "critical", 1.0, ev,
                       "No canonical tag. Add a self-referencing canonical so URL "
                       "variants of this page consolidate onto one address.")
    if not canonical.lower().startswith(("http://", "https://")):
        return Verdict("warn", 6.0, "major", 1.0, ev,
                       f"Canonical {canonical!r} is relative. Google's documentation asks "
                       f"for an absolute URL; a relative one is resolved unpredictably.")
    if same_page(canonical, url):
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("warn", 5.0, "major", 1.0,
                   {**ev, "canonical_normalised": normalise(canonical)},
                   f"This page points its canonical at {canonical}, so it asks Google to "
                   f"index that URL instead. Intentional for a duplicate; a silent "
                   f"de-indexing if not.")


# --------------------------------------------------------------------------
# Structured data
# --------------------------------------------------------------------------

@check("TECH-035", scope="page")
def check_structured_data(p: Any) -> Verdict:
    """TECH-035 - is there parseable structured data at all?"""
    blocks = getattr(p, "schema_blocks", []) or []
    errors = getattr(p, "schema_errors", []) or []
    types = sorted(set(_all_types(p)))
    ev = {"block_count": len(blocks), "types": types[:10], "parse_errors": len(errors),
          "error_examples": [str(e)[:120] for e in errors[:3]]}
    if errors and not blocks:
        return Verdict("fail", 1.0, "major", 1.0, ev,
                       f"Structured data is present but none of it parses "
                       f"({len(errors)} errors). Google discards unparseable JSON-LD "
                       f"entirely, so the page gets no benefit from it.")
    if not blocks:
        return Verdict("fail", 3.0, "major", 1.0, ev,
                       "No structured data. Schema is what makes a page eligible for rich "
                       "results and is the strongest signal for AI citation.")
    if errors:
        return Verdict("warn", 6.0, "major", 1.0, ev,
                       f"{len(blocks)} schema blocks parse but {len(errors)} do not.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("TECH-036", scope="page")
def check_schema_errors(p: Any) -> Verdict:
    """TECH-036 - JSON-LD that fails to parse."""
    errors = getattr(p, "schema_errors", []) or []
    ev = {"parse_errors": len(errors), "examples": [str(e)[:160] for e in errors[:3]]}
    if not errors:
        if not (getattr(p, "schema_blocks", []) or []):
            return Verdict("n_a", 0.0, "info", 1.0,
                           {**ev, "reason": "no structured data on the page"})
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("fail", 2.0, "major", 1.0, ev,
                   f"{len(errors)} JSON-LD blocks fail to parse. Google discards a block it "
                   f"cannot read, so every rich result it would have earned is lost.")


@check("TECH-093", scope="page")
def check_broken_structured_data(p: Any) -> Verdict:
    """TECH-093 - schema that parses but is missing properties Google REQUIRES.

    This is the quiet one: the block is valid JSON, Search Console reports it,
    and the rich result never appears because a required property is absent.
    """
    blocks = [b for b in (getattr(p, "schema_blocks", []) or []) if isinstance(b, dict)]
    if not blocks:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no structured data on the page"})
    incomplete: list[dict] = []
    for b in blocks:
        for t in _types(b):
            required = REQUIRED_PROPS.get(t)
            if not required:
                continue
            missing = [prop for prop in required if not b.get(prop)]
            if missing:
                incomplete.append({"type": t, "missing": missing})
    ev = {"blocks": len(blocks), "incomplete": incomplete[:5],
          "incomplete_count": len(incomplete)}
    if not incomplete:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    first = incomplete[0]
    return Verdict("fail", 4.0, "major", 0.9, ev,
                   f"{len(incomplete)} schema blocks are missing properties Google requires "
                   f"- {first['type']} has no {', '.join(first['missing'])}. The markup "
                   f"validates but the rich result cannot appear.")


@check("TECH-037", scope="page")
def check_rich_result_eligibility(p: Any) -> Verdict:
    """TECH-037 - does this page declare any type that can earn a rich result?"""
    types = set(_all_types(p))
    eligible = sorted(types & RICH_RESULT_TYPES)
    ev = {"declared_types": sorted(types)[:10], "rich_result_types": eligible}
    if not types:
        return Verdict("fail", 2.0, "major", 1.0, ev,
                       "No structured data, so the page cannot earn any rich result.")
    if not eligible:
        return Verdict("warn", 5.0, "minor", 1.0, ev,
                       f"Structured data declares {', '.join(sorted(types)[:3])}, none of "
                       f"which Google renders as a rich result. Add a type that matches "
                       f"the page - Article, Product, FAQPage or LocalBusiness.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("TECH-038", scope="page")
def check_breadcrumb_schema(p: Any) -> Verdict:
    """TECH-038 - BreadcrumbList replaces the raw URL in the search result with
    a readable hierarchy, which measurably lifts click-through."""
    types = set(_all_types(p))
    has_schema = "BreadcrumbList" in types
    has_nav = bool(getattr(p, "has_breadcrumb_nav", False))
    ev = {"breadcrumb_schema": has_schema, "breadcrumb_nav_present": has_nav}
    if has_schema:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if has_nav:
        return Verdict("warn", 5.0, "minor", 1.0, ev,
                       "The page renders a breadcrumb trail but declares no BreadcrumbList "
                       "schema, so Google cannot show it in the result. The markup is the "
                       "easy half - the navigation already exists.")
    return Verdict("warn", 6.0, "minor", 1.0, ev,
                   "No breadcrumb navigation or schema. Search results fall back to the raw "
                   "URL path.")


# --------------------------------------------------------------------------
# Social cards
# --------------------------------------------------------------------------

@check("TECH-086", scope="page")
def check_open_graph(p: Any) -> Verdict:
    """TECH-086 - the four properties ogp.me marks required.

    Unlike most SEO thresholds this one has an exact primary source, so the
    check is precise rather than conventional.
    """
    og = dict(getattr(p, "opengraph", {}) or {})
    present = {k.lower() for k in og}
    missing = [k for k in OG_REQUIRED if k not in present]
    ev = {"present": sorted(present)[:12], "missing_required": missing,
          "required_by": "ogp.me"}
    if not og:
        return Verdict("fail", 2.0, "minor", 1.0, ev,
                       "No Open Graph tags. Every share on Facebook, LinkedIn, WhatsApp or "
                       "Slack falls back to whatever those platforms scrape, which is "
                       "usually the wrong image and a truncated title.")
    if not missing:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    score = max(0.0, 10.0 - 2.5 * len(missing))
    return Verdict("warn" if len(missing) < 3 else "fail", score,
                   "minor" if len(missing) < 3 else "major", 1.0, ev,
                   f"Open Graph is missing {', '.join(missing)}, which ogp.me lists as "
                   f"required. Shares will render incompletely.")


@check("TECH-087", scope="page")
def check_twitter_card(p: Any) -> Verdict:
    """TECH-087 - twitter:card, plus the properties X documents as needed for
    a large-image card. Open Graph fills most gaps, so absence of OG too is
    what makes this a real problem."""
    tw = {k.lower(): v for k, v in (getattr(p, "twitter", {}) or {}).items()}
    og = {k.lower() for k in (getattr(p, "opengraph", {}) or {})}
    missing_required = [k for k in TWITTER_REQUIRED if k not in tw]
    missing_rec = [k for k in TWITTER_RECOMMENDED if k not in tw]
    ev = {"present": sorted(tw)[:10], "missing_required": missing_required,
          "missing_recommended": missing_rec, "open_graph_fallback": bool(og)}
    if not missing_required and not missing_rec:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if missing_required and not og:
        return Verdict("fail", 3.0, "minor", 1.0, ev,
                       "No twitter:card and no Open Graph to fall back on. Links shared on "
                       "X render as bare URLs.")
    if missing_required:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       "No twitter:card tag. X falls back to Open Graph, which this page "
                       "has, so the card renders but without large-image treatment.")
    return Verdict("warn", 8.0, "minor", 1.0, ev,
                   f"twitter:card is set but {', '.join(missing_rec)} missing.")


# --------------------------------------------------------------------------
# Security and structure
# --------------------------------------------------------------------------

@check("TECH-057", scope="page_http")
def check_mixed_content(cp: Any) -> Verdict:
    """TECH-057 - an HTTPS page loading resources over plain HTTP.

    Browsers block active mixed content outright, so the page renders broken;
    passive mixed content strips the padlock. Needs the RAW html, which is why
    this is page_http rather than page scope.
    """
    final = (getattr(cp, "final_url", "") or "").lower()
    if not final.startswith("https://"):
        return Verdict("n_a", 0.0, "info", 0.9,
                       {"reason": "page is not served over HTTPS, so mixed content "
                                  "does not apply", "scheme": final.split(":", 1)[0] or None})
    html = getattr(cp, "html", None)
    if not html:
        return Verdict("n_a", 0.0, "info", 0.0, {"reason": "no HTML body was captured"})
    found = _HTTP_RESOURCE.findall(html)
    # A link to an http:// page is not mixed content - only a loaded SUBRESOURCE
    # is. The regex already excludes bare <a href> by matching src/action/poster
    # plus href, so filter hrefs that are plainly navigational.
    resources = [u for u in found if not u.lower().endswith((".html", ".htm", "/"))]
    ev = {"http_resource_count": len(resources), "examples": sorted(set(resources))[:5]}
    if not resources:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("fail", max(0.0, 10.0 - len(resources)), "critical", 0.85, ev,
                   f"{len(resources)} resources load over plain HTTP on an HTTPS page. "
                   f"Browsers block scripts and stylesheets loaded this way, so the page "
                   f"can render broken, and the padlock is removed either way.")


@check("TECH-074", scope="page")
def check_semantic_html(p: Any) -> Verdict:
    """TECH-074 - semantic landmarks.

    This id previously carried a First Contentful Paint measurement.
    """
    counts = dict(getattr(p, "semantic_tag_counts", {}) or {})
    present = [t for t in _SEMANTIC_TAGS if counts.get(t)]
    ev = {"semantic_tags_present": present, "counts": counts}
    if not counts:
        return Verdict("fail", 3.0, "minor", 0.9, ev,
                       "The page uses no semantic landmarks (main, header, nav, article). "
                       "Crawlers and assistive technology cannot tell content from "
                       "navigation, so boilerplate is treated as page content.")
    if counts.get("main", 0) > 1:
        return Verdict("warn", 6.0, "minor", 0.9, ev,
                       f"{counts['main']} <main> elements. Exactly one is allowed; extras "
                       f"make the primary content ambiguous.")
    if "main" not in present:
        return Verdict("warn", 7.0, "minor", 0.9, ev,
                       "No <main> element. Wrap the primary content in one so crawlers can "
                       "separate it from header, nav and footer.")
    if len(present) >= 3:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("warn", 8.0, "minor", 0.9, ev,
                   f"Only {', '.join(present)} used. Add header, nav and footer landmarks.")


@check("TECH-067", scope="page")
def check_amp(p: Any) -> Verdict:
    """TECH-067 - AMP, if the page claims it.

    Google removed the AMP requirement for Top Stories in 2021, so a page with
    no AMP is not deficient. Only a page that CLAIMS AMP is checked.
    """
    if not getattr(p, "has_amp", False):
        return Verdict("n_a", 0.0, "info", 1.0,
                       {"has_amp": False,
                        "reason": "page does not use AMP; Google dropped the Top Stories "
                                  "AMP requirement in 2021, so this is not a defect"})
    canonical = getattr(p, "canonical", None)
    ev = {"has_amp": True, "canonical": canonical}
    if not canonical:
        return Verdict("warn", 5.0, "minor", 0.8, ev,
                       "The page declares AMP but has no canonical. An AMP page must point "
                       "at its canonical HTML version or the two compete.")
    return Verdict("pass", 10.0, "info", 0.8, ev)


@check("ON-081", scope="page")
def check_crawlability_on_page(p: Any) -> Verdict:
    """ON-081 - can this page be crawled and indexed, as the PAGE declares it?"""
    noindex = bool(getattr(p, "has_noindex", False))
    nofollow = bool(getattr(p, "has_nofollow_meta", False))
    robots_meta = getattr(p, "meta_robots", None)
    ev = {"meta_robots": robots_meta, "noindex": noindex, "nofollow": nofollow}
    if noindex:
        return Verdict("fail", 0.0, "critical", 1.0, ev,
                       "The page carries meta robots noindex, so it is excluded from Google "
                       "entirely.")
    if nofollow:
        return Verdict("warn", 5.0, "major", 1.0, ev,
                       "meta robots nofollow stops every link on this page passing signal.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("ON-098", scope="page")
def check_slug(p: Any) -> Verdict:
    """ON-098 - a readable slug.

    JUDGEMENT: the limits below are readability conventions, not Google rules.
    Google has said explicitly that URL words are a very small ranking factor;
    the real cost is a URL nobody will click or share.
    """
    from urllib.parse import urlsplit

    path = urlsplit(getattr(p, "url", "") or "").path
    slug = [s for s in path.split("/") if s]
    leaf = slug[-1] if slug else ""
    problems = []
    if "_" in leaf:
        problems.append("underscores (Google treats hyphens as word separators, not underscores)")
    if any(c.isupper() for c in leaf):
        problems.append("upper case (case-sensitive servers serve these as different URLs)")
    if len(leaf) > 60:
        problems.append(f"{len(leaf)} characters in the final segment")
    if len(slug) > 4:
        problems.append(f"{len(slug)} path levels deep")
    if re.search(r"\.(php|asp|aspx|jsp|cgi)$", leaf, re.I):
        problems.append("a file extension")
    if re.fullmatch(r"\d+", leaf):
        problems.append("a numeric id with no words")
    ev = {"path": path, "segments": len(slug), "leaf": leaf, "problems": problems,
          "threshold_basis": "readability convention; Google calls URL words a very small factor"}
    if not slug:
        return Verdict("n_a", 0.0, "info", 1.0, {**ev, "reason": "homepage has no slug"})
    if not problems:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("warn", max(4.0, 10.0 - 2.0 * len(problems)), "minor", 0.85, ev,
                   f"URL slug uses {'; '.join(problems)}. Rewrite as lowercase "
                   f"hyphen-separated words describing the page.")
