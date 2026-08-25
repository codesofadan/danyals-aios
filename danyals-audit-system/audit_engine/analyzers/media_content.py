"""The last checks whose inputs were already free.

Six checks that needed nothing the crawler was not already fetching. They were
ledgered as ``not_yet_built`` - the only reason that claims no blocker exists
beyond the work itself - so leaving them there while building waves that needed
new plumbing would have been the wrong order.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.context import CrawlContext
from audit_engine.analyzers.registry import check

SAMPLE = 5

# JUDGEMENT: Google has no published word count. This is the threshold below
# which a page reliably has too little to distinguish it from another page on
# the same subject, which is what "thin" actually costs a site.
THIN_WORDS = 150
# JUDGEMENT: a page can be short and fine (a contact page). Only a SITE with a
# large share of thin pages has a content problem worth reporting.
THIN_SHARE_WARN = 0.2
THIN_SHARE_FAIL = 0.4

_VIDEO_TAGS = re.compile(r"<video[\s>]|youtube\.com/embed|player\.vimeo\.com|wistia\.", re.I)
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif|svg|bmp|ico)(\?|$)", re.I)


def _no_crawl(ctx: CrawlContext) -> Verdict | None:
    if not ctx.crawled_urls:
        return Verdict("n_a", 0.0, "info", 0.0, {"reason": "no pages were crawled"})
    return None


def _parsed(ctx: CrawlContext) -> list[Any]:
    return [p for p in (getattr(cp, "parsed", None) for cp in ctx.by_url.values()) if p]


# --------------------------------------------------------------------------

@check("TECH-075", scope="site_crawled")
def check_thin_pages(ctx: CrawlContext) -> Verdict:
    """TECH-075 - pages with too little content to rank for anything.

    Reported as a SITE-level share rather than page by page: a short contact
    page is correct, and flagging it individually is how an audit fills a
    report with work nobody should do.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    counts = {}
    for url, cp in ctx.by_url.items():
        parsed = getattr(cp, "parsed", None)
        if parsed is None:
            continue
        counts[url] = int(getattr(parsed, "word_count", 0) or 0)
    if not counts:
        return Verdict("n_a", 0.0, "info", 0.0, {"reason": "no page bodies were parsed"})
    thin = {u: w for u, w in counts.items() if w < THIN_WORDS}
    share = len(thin) / len(counts)
    ev = {"pages_measured": len(counts), "thin_pages": len(thin),
          "share_thin": round(share, 3), "word_threshold": THIN_WORDS,
          "median_words": sorted(counts.values())[len(counts) // 2],
          "threshold_basis": "judgement; Google publishes no word count",
          "examples": dict(sorted(thin.items(), key=lambda kv: kv[1])[:SAMPLE])}
    if not thin:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if share < THIN_SHARE_WARN:
        return Verdict("pass", 9.0, "info", 0.85,
                       {**ev, "note": "a few short pages are normal - contact, thanks, "
                                      "policy pages are meant to be brief"})
    return Verdict(
        "fail" if share >= THIN_SHARE_FAIL else "warn",
        max(0.0, 10.0 - share * 15.0),
        "major" if share >= THIN_SHARE_FAIL else "minor", 0.85, ev,
        f"{len(thin)} of {len(counts)} crawled pages carry under {THIN_WORDS} words. "
        f"At that length a page has too little to distinguish it from any other page "
        f"on the same subject, so Google has no reason to prefer it.",
    )


@check("ON-020", scope="site_crawled")
def check_internal_topical_relevance(ctx: CrawlContext) -> Verdict:
    """ON-020 - do internal links connect pages about the same thing?

    A link between unrelated pages passes authority but no topical signal.
    Measured as title-term overlap between linked pairs, which is crude but
    honest - and the evidence says so rather than implying a semantic model.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na

    def terms(url: str) -> set[str]:
        parsed = getattr(ctx.by_url.get(url), "parsed", None)
        if parsed is None:
            return set()
        text = f"{getattr(parsed, 'title', '') or ''} {' '.join(getattr(parsed, 'h1s', []) or [])}"
        return set(re.findall(r"[a-z]{4,}", text.lower()))

    pairs = 0
    related = 0
    for src, dsts in ctx.outbound.items():
        s_terms = terms(src)
        if not s_terms:
            continue
        for dst in dsts:
            d_terms = terms(dst)
            if not d_terms:
                continue
            pairs += 1
            if s_terms & d_terms:
                related += 1
    ev = {"linked_pairs_compared": pairs, "topically_related": related,
          "method": "shared 4+ character terms between the two pages' titles and H1s - "
                    "a lexical overlap, not a semantic model"}
    if pairs < 5:
        return Verdict("n_a", 0.0, "info", 0.4,
                       {**ev, "reason": f"only {pairs} linked pairs had titles to compare; "
                                        f"too few to say anything about the site"})
    ratio = related / pairs
    ev["related_share"] = round(ratio, 3)
    if ratio >= 0.5:
        return Verdict("pass", 10.0, "info", 0.6, ev)
    return Verdict("warn" if ratio >= 0.25 else "fail",
                   round(ratio * 20.0, 1),
                   "minor" if ratio >= 0.25 else "major", 0.6, ev,
                   f"Only {round(ratio * 100)}% of internal links connect pages that share "
                   f"any topic wording. Links between unrelated pages pass authority but no "
                   f"topical signal, so they do not help either page rank for its subject.")


@check("TECH-094", scope="site_crawled")
def check_sitemap_xml_errors(ctx: CrawlContext) -> Verdict:
    """TECH-094 - a sitemap that fails to parse.

    Google's parser aborts on a malformed entity and silently drops every URL
    listed after that line, so a single bad character can hide most of a site.
    """
    sitemaps = list(getattr(ctx, "sitemaps", []) or [])
    if not sitemaps:
        return Verdict("n_a", 0.0, "info", 0.5,
                       {"reason": "no sitemap was fetched for this site"})
    broken = [{"url": getattr(sm, "url", None), "status": getattr(sm, "status_code", None),
               "error": str(getattr(sm, "error", ""))[:160]}
              for sm in sitemaps if getattr(sm, "error", None)]
    empty = [getattr(sm, "url", None) for sm in sitemaps
             if not getattr(sm, "error", None)
             and not getattr(sm, "urls", None)
             and not getattr(sm, "child_sitemaps", None)]
    total_urls = sum(len(getattr(sm, "urls", []) or []) for sm in sitemaps)
    ev = {"sitemaps_fetched": len(sitemaps), "parse_errors": len(broken),
          "empty_sitemaps": len(empty), "urls_listed": total_urls,
          "errors": broken[:3], "empty": empty[:3]}
    if broken:
        return Verdict("fail", 2.0, "major", 1.0, ev,
                       f"{len(broken)} of {len(sitemaps)} sitemaps failed to parse. Google's "
                       f"parser stops at the error and drops every URL after it, so most of "
                       f"the site can be invisible while the sitemap looks present.")
    if empty:
        return Verdict("warn", 6.0, "minor", 1.0, ev,
                       f"{len(empty)} sitemaps parsed but list no URLs and no child "
                       f"sitemaps.")
    return Verdict("pass", 10.0, "info", 1.0, ev)


@check("TECH-088", scope="site_crawled")
def check_image_crawlability(ctx: CrawlContext) -> Verdict:
    """TECH-088 - images robots.txt forbids Google from fetching.

    A blocked image cannot appear in Image Search, and on a page where the
    image IS the content that is a real loss.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    robots = ctx.robots
    if robots is None:
        return Verdict("n_a", 0.0, "info", 0.4,
                       {"reason": "robots.txt was not fetched, so nothing can be said "
                                  "about what it blocks"})
    seen: set[str] = set()
    blocked: list[str] = []
    for cp in ctx.by_url.values():
        parsed = getattr(cp, "parsed", None)
        base = getattr(cp, "final_url", "") or getattr(cp, "url", "") or ""
        for img in (getattr(parsed, "images", []) or []) if parsed else ():
            src = getattr(img, "src", "") or ""
            key = ctx.key(src, base=base)
            if not key or key in seen:
                continue
            seen.add(key)
            path = urlsplit(key).path or "/"
            try:
                if not robots.is_allowed(path):
                    blocked.append(key)
            except Exception:
                continue
    ev = {"images_seen": len(seen), "blocked_by_robots": len(blocked),
          "examples": sorted(blocked)[:SAMPLE]}
    if not seen:
        return Verdict("n_a", 0.0, "info", 0.6,
                       {**ev, "reason": "no images were found on the crawled pages"})
    if not blocked:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("warn", max(3.0, 10.0 - 10.0 * len(blocked) / len(seen)),
                   "minor", 0.9, ev,
                   f"robots.txt blocks {len(blocked)} of {len(seen)} images. Blocked images "
                   f"cannot appear in Image Search, and Google cannot use them to understand "
                   f"the page.")


@check("TECH-089", scope="site_crawled")
def check_image_indexing(ctx: CrawlContext) -> Verdict:
    """TECH-089 - the signals that let an image be indexed at all: alt text,
    a descriptive filename, and an image sitemap on an image-heavy site."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    total = 0
    no_alt = 0
    for cp in ctx.by_url.values():
        parsed = getattr(cp, "parsed", None)
        for img in (getattr(parsed, "images", []) or []) if parsed else ():
            total += 1
            if not (getattr(img, "alt", None) or "").strip():
                no_alt += 1
    has_image_sitemap = any(
        "image" in (getattr(sm, "url", "") or "").lower()
        for sm in (getattr(ctx, "sitemaps", []) or [])
    )
    ev = {"images_seen": total, "without_alt": no_alt,
          "image_sitemap_present": has_image_sitemap,
          "images_per_page": round(total / max(len(ctx.crawled_urls), 1), 1)}
    if not total:
        return Verdict("n_a", 0.0, "info", 0.6,
                       {**ev, "reason": "no images were found on the crawled pages"})
    share = no_alt / total
    if share == 0 and (has_image_sitemap or total < 30):
        return Verdict("pass", 10.0, "info", 0.85, ev)
    problems = []
    if share:
        problems.append(f"{no_alt} of {total} images have no alt text")
    if total >= 30 and not has_image_sitemap:
        problems.append("no image sitemap on an image-heavy site")
    return Verdict("warn" if share < 0.5 else "fail",
                   max(0.0, 10.0 - share * 10.0),
                   "minor" if share < 0.5 else "major", 0.85, ev,
                   "; ".join(problems).capitalize()
                   + ". Alt text is the only description Google has for an image, so "
                     "without it the image cannot be indexed for anything.")


@check("TECH-091", scope="site_crawled")
def check_video_indexing(ctx: CrawlContext) -> Verdict:
    """TECH-091 - video that Google cannot index.

    Reported only where video EXISTS. A dental practice with no video is not
    failing a video check, and saying so would be noise.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    pages_with_video = []
    with_schema = 0
    for url, cp in ctx.by_url.items():
        html = getattr(cp, "html", None) or ""
        parsed = getattr(cp, "parsed", None)
        if not _VIDEO_TAGS.search(html):
            continue
        pages_with_video.append(url)
        types: list[str] = []
        for block in (getattr(parsed, "schema_blocks", []) or []) if parsed else ():
            t = block.get("@type") if isinstance(block, dict) else None
            types.extend(t if isinstance(t, list) else [t] if t else [])
        if any(str(t) == "VideoObject" for t in types):
            with_schema += 1
    has_video_sitemap = any(
        "video" in (getattr(sm, "url", "") or "").lower()
        for sm in (getattr(ctx, "sitemaps", []) or [])
    )
    ev = {"pages_with_video": len(pages_with_video),
          "with_video_object_schema": with_schema,
          "video_sitemap_present": has_video_sitemap,
          "examples": sorted(pages_with_video)[:SAMPLE]}
    if not pages_with_video:
        return Verdict("n_a", 0.0, "info", 1.0,
                       {**ev, "reason": "no video was found on the crawled pages, so there "
                                        "is nothing to index"})
    missing = len(pages_with_video) - with_schema
    if not missing:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("warn", max(3.0, 10.0 - 7.0 * missing / len(pages_with_video)),
                   "minor", 0.85, ev,
                   f"{missing} of {len(pages_with_video)} pages with video carry no "
                   f"VideoObject schema. Google needs it to know a video exists, what it "
                   f"shows and how long it runs; without it the video cannot appear in "
                   f"video results.")
