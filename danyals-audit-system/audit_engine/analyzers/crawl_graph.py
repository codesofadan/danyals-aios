"""Site-wide checks over the crawl graph.

Everything here needs the whole crawl rather than one page: which URLs are
orphaned, which internal links are broken, whether redirects chain or loop,
whether the sitemap agrees with what was actually fetched.

Every check reads the graph built once in ``context.py`` through the single
normalisation in ``urls.py``. These checks used to be impossible to write
correctly because each analyzer derived its own graph and they disagreed with
each other about what counted as the same page.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.context import UNREACHABLE, CrawlContext
from audit_engine.analyzers.registry import check
from audit_engine.analyzers.urls import normalise

#: Cap on URLs listed in evidence. The full set lives in the workbook; a
#: finding carries a sample plus the true count so a report never implies the
#: sample IS the total.
SAMPLE = 5

# JUDGEMENT: Google's current redirect documentation states no hop limit at
# all - the "5 hops" figure repeated everywhere is community lore. Googlebot
# is documented to follow up to 10 hops in one crawl attempt, so 3 is an
# adopted convention for "this is costing crawl budget", not a Google rule.
REDIRECT_CHAIN_WARN_HOPS = 3

_SEARCH_PATHS = re.compile(r"/(search|suche|recherche|resultat)s?(/|$)", re.I)
_SEARCH_PARAMS = frozenset({"s", "q", "query", "search", "keyword", "keywords"})
# Parameters that generate near-infinite permutations of one page.
_FACET_PARAMS = frozenset({
    "filter", "filters", "sort", "sort_by", "order", "orderby", "color",
    "colour", "size", "brand", "price", "min_price", "max_price", "rating",
    "view", "layout", "per_page", "limit", "offset", "attribute_pa_color",
})


def _sample(urls: Any) -> list[str]:
    return sorted(urls)[:SAMPLE]


def _pages(ctx: CrawlContext) -> list[Any]:
    return list(ctx.by_url.values())


def _status(cp: Any) -> int:
    return int(getattr(cp, "http_status", 0) or 0)


def _no_crawl(ctx: CrawlContext) -> Verdict | None:
    if not ctx.crawled_urls:
        return Verdict("n_a", 0.0, "info", 0.0, {"reason": "no pages were crawled"})
    return None


# --------------------------------------------------------------------------
# Broken pages
# --------------------------------------------------------------------------

@check("TECH-012", scope="site_crawled")
def check_404_errors(ctx: CrawlContext) -> Verdict:
    """TECH-012 - internal links that lead to a 404."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    broken = {u for u in ctx.crawled_urls if _status(ctx.by_url[u]) == 404}
    # A 404 nothing links to costs nothing; one that is linked wastes crawl
    # budget and strands a visitor.
    linked = {u: sorted(ctx.inbound.get(u, ())) for u in broken if ctx.inbound.get(u)}
    ev = {"pages_crawled": len(ctx.crawled_urls), "not_found_count": len(broken),
          "linked_not_found_count": len(linked),
          "examples": _sample(broken),
          "example_sources": {u: v[:3] for u, v in list(linked.items())[:3]}}
    if not broken:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if not linked:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       f"{len(broken)} URLs return 404 but nothing links to them. "
                       f"They cost crawl budget only if they remain in the sitemap.")
    return Verdict("fail", max(0.0, 10.0 - 10.0 * len(linked) / max(len(ctx.crawled_urls), 1)),
                   "critical", 1.0, ev,
                   f"{len(linked)} of {len(broken)} broken URLs are linked from elsewhere on "
                   f"the site. Every one strands a visitor and wastes crawl budget. Fix or "
                   f"remove the links, starting with {_sample(linked)[0]}.")


@check("TECH-014", scope="site_crawled")
def check_5xx_errors(ctx: CrawlContext) -> Verdict:
    """TECH-014 - a 5xx tells Google the site is broken, not the page."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    bad = {u: _status(ctx.by_url[u]) for u in ctx.crawled_urls if 500 <= _status(ctx.by_url[u]) < 600}
    ev = {"pages_crawled": len(ctx.crawled_urls), "server_error_count": len(bad),
          "examples": dict(list(bad.items())[:SAMPLE])}
    if not bad:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("fail", 0.0, "critical", 1.0, ev,
                   f"{len(bad)} of {len(ctx.crawled_urls)} crawled URLs returned a server "
                   f"error. Google slows crawling of a site returning 5xx and can drop "
                   f"affected pages from the index entirely.")


@check("TECH-013", scope="site_crawled")
def check_soft_404(ctx: CrawlContext) -> Verdict:
    """TECH-013 - a page that SAYS not found but returns 200.

    Google indexes it, then discovers the contradiction and distrusts status
    codes across the site.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    phrases = ("page not found", "404 error", "not be found", "no longer exists",
               "doesn't exist", "does not exist", "page you requested")
    suspects = []
    for u in ctx.crawled_urls:
        cp = ctx.by_url[u]
        if _status(cp) != 200:
            continue
        parsed = getattr(cp, "parsed", None)
        if parsed is None:
            continue
        hay = f"{parsed.title or ''} {' '.join(parsed.h1s or [])}".lower()
        if any(p in hay for p in phrases) or ((parsed.word_count or 0) < 50 and any(
            p in (parsed.body_text or "").lower()[:600] for p in phrases
        )):
            suspects.append(u)
    ev = {"pages_crawled": len(ctx.crawled_urls), "soft_404_count": len(suspects),
          "examples": _sample(suspects)}
    if not suspects:
        return Verdict("pass", 10.0, "info", 0.8, ev)
    return Verdict("fail", 3.0, "major", 0.8, ev,
                   f"{len(suspects)} pages return HTTP 200 while telling the visitor the "
                   f"page was not found. Return a real 404 so Google removes them instead "
                   f"of indexing an error page.")


# --------------------------------------------------------------------------
# Redirects
# --------------------------------------------------------------------------

def _hops(cp: Any) -> list[Any]:
    return list(getattr(cp, "redirect_hops", []) or [])


@check("TECH-016", scope="site_crawled")
def check_redirect_loops(ctx: CrawlContext) -> Verdict:
    """TECH-016 - a redirect that returns to a URL already in its own chain."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    loops = []
    for u in ctx.crawled_urls:
        cp = ctx.by_url[u]
        seen: list[str] = []
        for hop in _hops(cp):
            k = normalise(getattr(hop, "url", "") or "", policy=ctx.policy)
            if k and k in seen:
                loops.append(u)
                break
            if k:
                seen.append(k)
    ev = {"redirect_loop_count": len(loops), "examples": _sample(loops)}
    if not loops:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("fail", 0.0, "critical", 1.0, ev,
                   f"{len(loops)} URLs redirect in a loop. Neither a browser nor Googlebot "
                   f"can ever reach the content, so the pages cannot be indexed at all.")


@check("TECH-017", scope="site_crawled")
def check_301_chains(ctx: CrawlContext) -> Verdict:
    """TECH-017 - permanent redirects should land in one hop.

    Every extra hop is a round trip for the visitor and a crawl-budget cost.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    chains = {u: len(_hops(ctx.by_url[u])) for u in ctx.crawled_urls if len(_hops(ctx.by_url[u])) > 1}
    long_chains = {u: n for u, n in chains.items() if n >= REDIRECT_CHAIN_WARN_HOPS}
    ev = {"redirecting_urls": sum(1 for u in ctx.crawled_urls if _hops(ctx.by_url[u])),
          "multi_hop_count": len(chains), "long_chain_count": len(long_chains),
          "warn_threshold_hops": REDIRECT_CHAIN_WARN_HOPS,
          "threshold_basis": "adopted convention; Google publishes no hop limit",
          "examples": dict(list(chains.items())[:SAMPLE])}
    if not chains:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if not long_chains:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       f"{len(chains)} URLs redirect through more than one hop. Point each "
                       f"source directly at its final destination.")
    return Verdict("fail", 4.0, "major", 1.0, ev,
                   f"{len(long_chains)} URLs redirect through {REDIRECT_CHAIN_WARN_HOPS} or "
                   f"more hops. Collapse each chain to a single 301.")


@check("TECH-018", scope="site_crawled")
def check_302_misuse(ctx: CrawlContext) -> Verdict:
    """TECH-018 - a 302 says "this move is temporary", so Google keeps the OLD
    URL indexed and passes no signal to the new one. Used for a permanent move
    it silently strands the destination."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    temporary = {}
    for u in ctx.crawled_urls:
        for hop in _hops(ctx.by_url[u]):
            st = int(getattr(hop, "status", 0) or 0)
            if st in (302, 303, 307):
                temporary.setdefault(u, []).append(st)
    ev = {"temporary_redirect_count": len(temporary),
          "examples": dict(list(temporary.items())[:SAMPLE])}
    if not temporary:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("warn", 5.0, "major", 1.0, ev,
                   f"{len(temporary)} URLs use a temporary redirect (302/303/307). If the "
                   f"move is permanent, use 301 so the destination inherits the ranking "
                   f"signal instead of the old URL keeping it.")


# --------------------------------------------------------------------------
# Reachability
# --------------------------------------------------------------------------

@check("TECH-009", scope="site_crawled")
def check_orphan_urls(ctx: CrawlContext) -> Verdict:
    """TECH-009 - a page in the sitemap that nothing links to.

    Google reaches it only through the sitemap, which carries almost no
    ranking weight on its own.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    orphans = ctx.orphans()
    in_sitemap = orphans & ctx.sitemap_urls if ctx.sitemap_urls else set()
    ev = {"pages_crawled": len(ctx.crawled_urls), "orphan_count": len(orphans),
          "orphans_in_sitemap": len(in_sitemap), "examples": _sample(orphans),
          "crawl_was_partial": ctx.is_partial,
          "crawl_coverage": round(ctx.coverage, 3)}
    if ctx.is_partial and orphans:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "crawl covered "
                                        f"{round(ctx.coverage * 100)}% of discovered URLs; "
                                        "a page linked only from an uncrawled page would "
                                        "look orphaned"})
    if not orphans:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    share = len(orphans) / max(len(ctx.crawled_urls), 1)
    return Verdict(
        "fail" if share > 0.2 else "warn",
        max(0.0, 10.0 - share * 20.0),
        "major" if share > 0.2 else "minor", 0.9, ev,
        f"{len(orphans)} of {len(ctx.crawled_urls)} crawled pages have no internal link "
        f"pointing at them. Add links from relevant pages; a sitemap entry alone gives "
        f"almost no ranking weight.",
    )


@check("TECH-026", scope="site_crawled")
def check_crawl_traps(ctx: CrawlContext) -> Verdict:
    """TECH-026 - a URL space that generates itself forever.

    Two signatures: a path segment repeated (``/a/b/a/b/a/``), and one page
    reachable under an unbounded number of parameter permutations.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    repeating = []
    for u in ctx.discovered_urls:
        segs = [s for s in urlsplit(u).path.split("/") if s]
        if len(segs) >= 4:
            counts = Counter(segs)
            if any(c >= 3 for c in counts.values()):
                repeating.append(u)
    by_path: dict[str, int] = Counter()
    for u in ctx.discovered_urls:
        parts = urlsplit(u)
        if parts.query:
            by_path[f"{parts.scheme}://{parts.netloc}{parts.path}"] += 1
    exploding = {p: n for p, n in by_path.items() if n >= 25}
    ev = {"repeating_segment_urls": len(repeating), "examples": _sample(repeating),
          "paths_with_many_variants": dict(list(exploding.items())[:3])}
    if not repeating and not exploding:
        return Verdict("pass", 10.0, "info", 0.8, ev)
    return Verdict("fail" if repeating else "warn",
                   3.0 if repeating else 6.0,
                   "critical" if repeating else "major", 0.8, ev,
                   "URLs repeat a path segment, which usually means relative links resolve "
                   "recursively and generate an unbounded URL space."
                   if repeating else
                   f"{len(exploding)} paths appear under 25 or more parameter combinations. "
                   f"Google will spend crawl budget enumerating them.")


# --------------------------------------------------------------------------
# Duplication and URL hygiene
# --------------------------------------------------------------------------

@check("TECH-022", scope="site_crawled")
def check_duplicate_urls(ctx: CrawlContext) -> Verdict:
    """TECH-022 - several raw URLs that are the SAME page.

    Uses the one normalisation (O-2), so this cannot disagree with what the
    orphan and duplicate-content checks consider one page.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    seen: dict[str, list[str]] = {}
    for raw in ctx.raw_urls:
        k = normalise(raw, policy=ctx.policy)
        if k:
            seen.setdefault(k, []).append(raw)
    dupes = {k: v for k, v in seen.items() if len({*v}) > 1}
    ev = {"distinct_pages": len(seen), "duplicate_groups": len(dupes),
          "examples": {k: v[:3] for k, v in list(dupes.items())[:3]}}
    if not dupes:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    return Verdict("warn", 6.0, "major", 1.0, ev,
                   f"{len(dupes)} pages are reachable at more than one URL. Pick one form, "
                   f"301 the rest to it, and make the canonical agree.")


@check("TECH-076", scope="site_crawled")
def check_duplicate_pages(ctx: CrawlContext) -> Verdict:
    """TECH-076 - different URLs serving byte-identical body text."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    by_hash: dict[str, list[str]] = {}
    for u in ctx.crawled_urls:
        parsed = getattr(ctx.by_url[u], "parsed", None)
        text = (getattr(parsed, "body_text", "") or "").strip() if parsed else ""
        if len(text) < 200:
            continue
        h = hashlib.sha1(" ".join(text.split()).encode("utf-8", "ignore")).hexdigest()
        by_hash.setdefault(h, []).append(u)
    groups = {h: us for h, us in by_hash.items() if len(us) > 1}
    dupe_pages = sum(len(us) for us in groups.values())
    ev = {"pages_compared": len(by_hash), "duplicate_groups": len(groups),
          "pages_in_a_duplicate_group": dupe_pages,
          "examples": [sorted(us)[:3] for us in list(groups.values())[:3]]}
    if not groups:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("fail", max(0.0, 10.0 - 10.0 * dupe_pages / max(len(by_hash), 1)),
                   "major", 0.9, ev,
                   f"{dupe_pages} pages share identical body copy across {len(groups)} "
                   f"groups. Google picks one and suppresses the rest; canonicalise or "
                   f"differentiate them.")


@check("TECH-023", scope="site_crawled")
def check_url_parameter_indexing(ctx: CrawlContext) -> Verdict:
    """TECH-023 - indexable URLs carrying parameters that change nothing."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    tracked = []
    for raw in ctx.raw_urls:
        q = dict(parse_qsl(urlsplit(raw).query, keep_blank_values=True))
        if not q:
            continue
        # If normalising the URL yields the same page as stripping the query
        # entirely, every parameter on it was tracking - so this URL is a
        # duplicate entry point for a page that already exists.
        if normalise(raw, policy=ctx.policy) == normalise(raw.split("?")[0], policy=ctx.policy):
            tracked.append(raw)
    ev = {"parameterised_urls": len(tracked), "examples": _sample(tracked)}
    if not tracked:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("warn", 6.0, "major", 0.9, ev,
                   f"{len(tracked)} crawled URLs carry query parameters that produce the "
                   f"same content. Add a self-referencing canonical to the clean URL.")


@check("TECH-024", scope="site_crawled")
def check_faceted_navigation(ctx: CrawlContext) -> Verdict:
    """TECH-024 - filter and sort parameters multiply one listing into
    thousands of near-identical URLs, all competing with each other."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    faceted = []
    params_seen: Counter = Counter()
    for u in ctx.discovered_urls:
        q = dict(parse_qsl(urlsplit(u).query, keep_blank_values=True))
        hits = [k for k in q if k.lower() in _FACET_PARAMS]
        if hits:
            faceted.append(u)
            params_seen.update(k.lower() for k in hits)
    ev = {"faceted_urls": len(faceted), "parameters": dict(params_seen.most_common(6)),
          "examples": _sample(faceted)}
    if not faceted:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict("warn" if len(faceted) < 25 else "fail",
                   6.0 if len(faceted) < 25 else 3.0,
                   "major", 0.85, ev,
                   f"{len(faceted)} URLs use filter or sort parameters "
                   f"({', '.join(list(params_seen)[:4])}). Each combination is a separate "
                   f"URL competing with the clean listing; canonicalise them to it or block "
                   f"the parameters in robots.txt.")


@check("TECH-027", scope="site_crawled")
def check_search_page_indexing(ctx: CrawlContext) -> Verdict:
    """TECH-027 - internal search results are thin, unbounded, and explicitly
    named in Google's own quality guidance as content to keep out of the index."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    hits = []
    for u in ctx.discovered_urls:
        parts = urlsplit(u)
        q = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
        if _SEARCH_PATHS.search(parts.path) or (q & _SEARCH_PARAMS):
            hits.append(u)
    indexable = []
    for u in hits:
        cp = ctx.by_url.get(u)
        parsed = getattr(cp, "parsed", None) if cp else None
        if parsed is not None and not getattr(parsed, "has_noindex", False):
            indexable.append(u)
    ev = {"search_urls_found": len(hits), "indexable_search_urls": len(indexable),
          "examples": _sample(hits)}
    if not hits:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    if not indexable:
        return Verdict("pass", 9.0, "info", 0.85,
                       {**ev, "note": "search URLs exist but carry noindex"})
    return Verdict("fail", 3.0, "major", 0.85, ev,
                   f"{len(indexable)} internal search result URLs are indexable. Add "
                   f"noindex to search templates; Google's guidance names these explicitly.")


# --------------------------------------------------------------------------
# Domain form consistency
# --------------------------------------------------------------------------

def _form_consistency(ctx: CrawlContext, key: str, describe: str) -> Verdict:
    """Shared body for the www and trailing-slash consistency checks."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    variants: Counter = Counter()
    for cp in _pages(ctx):
        final = getattr(cp, "final_url", "") or getattr(cp, "url", "") or ""
        if not final:
            continue
        if key == "www":
            variants["www" if urlsplit(final).netloc.lower().startswith("www.") else "bare"] += 1
        else:
            path = urlsplit(final).path
            if path in ("", "/"):
                continue
            variants["slash" if path.endswith("/") else "no-slash"] += 1
    ev = {"variants": dict(variants)}
    if len(variants) <= 1:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    minority = min(variants.values())
    total = sum(variants.values())
    return Verdict("warn", max(4.0, 10.0 - 10.0 * minority / max(total, 1)), "major", 0.9, ev,
                   f"The site serves both {describe} ({dict(variants)}). Pick one and 301 "
                   f"the other; serving both splits ranking signals between two URLs for "
                   f"every page.")


@check("TECH-059", scope="site_crawled")
def check_www_consistency(ctx: CrawlContext) -> Verdict:
    """TECH-059 - www and non-www must not both serve content."""
    return _form_consistency(ctx, "www", "www and non-www URLs")


@check("TECH-060", scope="site_crawled")
def check_trailing_slash_consistency(ctx: CrawlContext) -> Verdict:
    """TECH-060 - one URL form per page.

    Normalisation treats /a and /a/ as one page (O-2), so this reports the
    INCONSISTENCY without inventing duplicate-content findings for it.
    """
    return _form_consistency(ctx, "slash", "trailing-slash and non-trailing-slash URLs")


# --------------------------------------------------------------------------
# Internal linking
# --------------------------------------------------------------------------

@check("TECH-068", scope="site_crawled")
def check_internal_linking_crawl(ctx: CrawlContext) -> Verdict:
    """TECH-068 - how deep the site is, measured in clicks from the homepage."""
    if (na := _no_crawl(ctx)) is not None:
        return na
    depths = [ctx.depth.get(u, UNREACHABLE) for u in ctx.crawled_urls]
    reachable = [d for d in depths if d < UNREACHABLE]
    unreachable = len(depths) - len(reachable)
    dist = Counter(reachable)
    # JUDGEMENT: three clicks is the widely-taught target and matches how
    # crawl priority decays with depth in practice. It is a convention, not a
    # published Google threshold.
    deep = [d for d in reachable if d > 3]
    ev = {"pages_crawled": len(ctx.crawled_urls),
          "depth_distribution": {str(k): v for k, v in sorted(dist.items())},
          "unreachable_from_homepage": unreachable,
          "deeper_than_3_clicks": len(deep),
          "max_depth": max(reachable) if reachable else None,
          "crawl_was_partial": ctx.is_partial,
          "crawl_coverage": round(ctx.coverage, 3),
          "threshold_basis": "3 clicks is an adopted convention, not a Google rule"}
    if ctx.is_partial:
        # Not measurable: a page looks unreachable because the page linking to
        # it was never fetched. This is our page cap, not their site.
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "crawl covered "
                                        f"{round(ctx.coverage * 100)}% of discovered URLs; "
                                        "click depth needs a complete crawl"})
    if not reachable:
        return Verdict("fail", 0.0, "critical", 0.9, ev,
                       "No crawled page is reachable by following links from the homepage.")
    if unreachable == 0 and not deep:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    share = (unreachable + len(deep)) / max(len(ctx.crawled_urls), 1)
    return Verdict("fail" if share > 0.3 else "warn",
                   max(0.0, 10.0 - share * 12.0),
                   "major" if share > 0.3 else "minor", 0.9, ev,
                   f"{unreachable} pages cannot be reached from the homepage and "
                   f"{len(deep)} sit deeper than 3 clicks. Link them from a relevant hub "
                   f"page to shorten the path.")


@check("TECH-069", scope="site_crawled")
def check_link_equity_flow(ctx: CrawlContext) -> Verdict:
    """TECH-069 - is internal link weight spread, or pooled on a few pages?

    This id previously carried an HTTP-version measurement.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    counts = {u: len(ctx.inbound.get(u, ())) for u in ctx.crawled_urls if u != ctx.home}
    if not counts:
        return Verdict("n_a", 0.0, "info", 0.5,
                       {"reason": "only the homepage was crawled"})
    values = sorted(counts.values())
    total = sum(values)
    avg = total / len(values)
    zero = [u for u, n in counts.items() if n == 0]
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    # Share of all internal links landing on the top 10% of pages.
    top_decile = max(1, len(values) // 10)
    concentration = sum(values[-top_decile:]) / total if total else 0.0
    ev = {"pages": len(values), "internal_links": total,
          "avg_inbound": round(avg, 2), "pages_with_no_inbound": len(zero),
          "top_decile_share": round(concentration, 3),
          "most_linked": [{"url": u, "inbound": n} for u, n in top]}
    if total == 0:
        return Verdict("fail", 0.0, "major", 0.9, ev,
                       "No internal links were found between crawled pages. Every page is "
                       "an island, so no ranking signal moves through the site.")
    if concentration > 0.6 or len(zero) > len(values) * 0.3:
        return Verdict("warn", 5.0, "major", 0.9, ev,
                       f"{round(concentration * 100)}% of internal links point at the top "
                       f"10% of pages and {len(zero)} pages receive none. Spread links "
                       f"toward the pages you want to rank.")
    return Verdict("pass", 10.0, "info", 0.9, ev)


# --------------------------------------------------------------------------
# Sitemap agreement
# --------------------------------------------------------------------------

@check("TECH-004", scope="site_crawled")
def check_sitemap_url_status(ctx: CrawlContext) -> Verdict:
    """TECH-004 - every sitemap URL should return 200.

    A sitemap is a set of promises. A 404 or a redirect in it tells Google the
    promises are unreliable and reduces how much of it is trusted.
    """
    if not ctx.sitemap_urls:
        return Verdict("n_a", 0.0, "info", 0.6,
                       {"reason": "no sitemap URLs were discovered"})
    checked = {u: ctx.by_url[u] for u in ctx.sitemap_urls if u in ctx.by_url}
    if not checked:
        return Verdict("n_a", 0.0, "info", 0.5,
                       {"reason": "no sitemap URL was crawled in this run",
                        "sitemap_urls": len(ctx.sitemap_urls)})
    bad = {u: _status(cp) for u, cp in checked.items() if _status(cp) != 200}
    redirected = {u for u, cp in checked.items() if _hops(cp)}
    ev = {"sitemap_urls": len(ctx.sitemap_urls), "checked": len(checked),
          "non_200": len(bad), "redirecting": len(redirected),
          "examples": dict(list(bad.items())[:SAMPLE])}
    if not bad and not redirected:
        return Verdict("pass", 10.0, "info", 1.0, ev)
    if not bad:
        return Verdict("warn", 7.0, "minor", 1.0, ev,
                       f"{len(redirected)} sitemap URLs redirect. List the final URL "
                       f"directly so Google is not asked to follow a hop for every entry.")
    return Verdict("fail", max(0.0, 10.0 - 10.0 * len(bad) / len(checked)), "major", 1.0, ev,
                   f"{len(bad)} of {len(checked)} checked sitemap URLs do not return 200. "
                   f"A sitemap full of broken promises is trusted less as a whole.")


@check("TECH-003", scope="site_crawled")
def check_sitemap_indexability(ctx: CrawlContext) -> Verdict:
    """TECH-003 - a sitemap must not list URLs it also forbids indexing.

    Listing a noindex URL is a direct contradiction: the sitemap asks Google to
    index it and the page tells Google not to.
    """
    if not ctx.sitemap_urls:
        return Verdict("n_a", 0.0, "info", 0.6,
                       {"reason": "no sitemap URLs were discovered"})
    contradictions = []
    blocked = []
    robots = ctx.robots
    for u in ctx.sitemap_urls:
        cp = ctx.by_url.get(u)
        parsed = getattr(cp, "parsed", None) if cp else None
        if parsed is not None and getattr(parsed, "has_noindex", False):
            contradictions.append(u)
        if robots is not None:
            try:
                if not robots.is_allowed(urlsplit(u).path or "/"):
                    blocked.append(u)
            except Exception:
                pass
    ev = {"sitemap_urls": len(ctx.sitemap_urls),
          "noindex_in_sitemap": len(contradictions),
          "robots_blocked_in_sitemap": len(blocked),
          "examples": _sample(contradictions + blocked)}
    if not contradictions and not blocked:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict("fail", 3.0, "major", 0.9, ev,
                   f"{len(contradictions)} sitemap URLs carry noindex and {len(blocked)} are "
                   f"blocked by robots.txt. The sitemap asks Google to index pages the site "
                   f"then forbids; remove them from the sitemap or lift the block.")


@check("TECH-083", scope="site_crawled")
def check_hidden_pages(ctx: CrawlContext) -> Verdict:
    """TECH-083 - pages reachable only if you already know the URL.

    Not inherently a defect: a thank-you page SHOULD be unlinked. It is
    reported so an operator can confirm the exposure is intended.
    """
    if (na := _no_crawl(ctx)) is not None:
        return na
    hidden = {
        u for u in ctx.crawled_urls
        if u != ctx.home and not ctx.inbound.get(u) and u not in ctx.sitemap_urls
    }
    ev = {"hidden_count": len(hidden), "examples": _sample(hidden),
          "crawl_was_partial": ctx.is_partial}
    if ctx.is_partial and hidden:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": "crawl was partial; a page linked only from an "
                                        "uncrawled page would look hidden"})
    if not hidden:
        return Verdict("pass", 10.0, "info", 0.8, ev)
    return Verdict("warn", 7.0, "minor", 0.8, ev,
                   f"{len(hidden)} crawled pages have no internal link and no sitemap "
                   f"entry. Confirm each is meant to be reachable; anything public and "
                   f"unlisted is invisible to Google.")
