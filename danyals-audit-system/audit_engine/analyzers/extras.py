"""Free deterministic feature analyzers (no API spend).

This module holds shared helpers and site-wide checks that do not fit into a
single per-page analyzer. Per-page checks now live in onpage.py.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Iterable
from urllib.parse import urlparse

import httpx

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.crawlers.basic import CrawledPage
from audit_engine.parsers.html import ParsedHTML


# ---------- F-2.2.3 Heading-as-question detection ----------

_QUESTION_STARTS = re.compile(
    r"^\s*(what|why|how|when|where|who|which|can|does|do|is|are|should|will|would)\b",
    re.IGNORECASE,
)


def check_heading_questions(p: ParsedHTML) -> Verdict:
    """F-2.2.3 - share of headings posed as questions (AEO-friendly)."""
    headings = [h.text for h in p.headings if h.level in (2, 3)]
    if not headings:
        return Verdict("n_a", 0.0, "info", 1.0, {"heading_count": 0})
    questions = sum(1 for h in headings if h.endswith("?") or _QUESTION_STARTS.match(h))
    ratio = questions / len(headings)
    if ratio >= 0.3:
        return Verdict("pass", 10.0, "info", 0.9,
                       {"heading_count": len(headings), "question_count": questions, "ratio": round(ratio, 2)})
    if ratio >= 0.1:
        return Verdict("warn", 6.0, "minor", 0.8,
                       {"heading_count": len(headings), "question_count": questions, "ratio": round(ratio, 2)},
                       "Reframe more H2/H3 as questions for AI Overview / PAA eligibility.")
    return Verdict("warn", 4.0, "minor", 0.8,
                   {"heading_count": len(headings), "question_count": questions, "ratio": round(ratio, 2)},
                   "No headings are framed as questions. Convert 2-3 H2s to question form to improve AI Overview citation odds.")


# ---------- F-2.2.4 H1-to-title alignment ----------

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with", "by", "at", "is", "are", "be"}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def check_h1_title_alignment(p: ParsedHTML) -> Verdict:
    """F-2.2.4 - H1 and <title> should share the same central entity."""
    if not p.title or not p.h1s:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "missing title or h1"})
    t1, t2 = _tokens(p.title), _tokens(p.h1s[0])
    if not t1 or not t2:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no significant tokens"})
    overlap = len(t1 & t2) / max(len(t1 | t2), 1)
    if overlap >= 0.5:
        return Verdict("pass", 10.0, "info", 0.85, {"jaccard": round(overlap, 2)})
    if overlap >= 0.25:
        return Verdict("warn", 6.0, "minor", 0.8, {"jaccard": round(overlap, 2)},
                       "H1 and title share only some keywords; align them around the same entity.")
    return Verdict("fail", 3.0, "major", 0.85, {"jaccard": round(overlap, 2)},
                   "H1 and title target different concepts. Rewrite so both lead with the same primary entity.")


# ---------- F-2.3.6 Readability (Flesch-Kincaid Reading Ease) ----------

_SENT_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"[A-Za-z]+")
_VOWEL_RUN = re.compile(r"[aeiouy]+", re.IGNORECASE)


def _syllable_count(word: str) -> int:
    word = word.lower().rstrip("e")
    runs = _VOWEL_RUN.findall(word)
    return max(len(runs), 1)


def check_readability(p: ParsedHTML) -> Verdict:
    """F-2.3.6 - Flesch Reading Ease score on body text."""
    text = (p.body_text or "")[:20000]
    if not text or len(text) < 200:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "too little text"})
    sentences = max(len([s for s in _SENT_RE.split(text) if s.strip()]), 1)
    words = _WORD_RE.findall(text)
    if len(words) < 50:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "too few words"})
    syllables = sum(_syllable_count(w) for w in words)
    # Flesch Reading Ease: 206.835 - 1.015*(words/sentences) - 84.6*(syllables/words)
    fre = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    fre = max(0.0, min(100.0, fre))
    # Scoring: 60-70 ideal "Plain English". Lower = harder.
    if fre >= 60:
        score = 10.0
        verdict = "pass"
        sev = "info"
        rem = None
    elif fre >= 50:
        score = 7.0
        verdict = "warn"
        sev = "minor"
        rem = f"Flesch Reading Ease {fre:.0f} (fairly difficult); shorten sentences and prefer common words."
    elif fre >= 30:
        score = 4.0
        verdict = "warn"
        sev = "major"
        rem = f"Flesch Reading Ease {fre:.0f} (difficult); break long sentences and replace jargon."
    else:
        score = 2.0
        verdict = "fail"
        sev = "major"
        rem = f"Flesch Reading Ease {fre:.0f} (very difficult); rewrite at an 8th-grade reading level."
    return Verdict(verdict, score, sev, 0.8,
                   {"flesch_reading_ease": round(fre, 1), "words": len(words), "sentences": sentences},
                   rem)


# ---------- F-2.3.8 Duplicate content detection (Jaccard shingles) ----------

def _shingles(text: str, k: int = 5) -> set[int]:
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < k:
        return set()
    return {
        hash(" ".join(tokens[i : i + k]))
        for i in range(0, len(tokens) - k + 1)
    }


def check_duplicate_content(pages: list[ParsedHTML]) -> Verdict:
    """F-2.3.8 - cross-page text overlap by k-shingle Jaccard."""
    candidates = [(p.url, _shingles(p.body_text)) for p in pages if p.body_text and len(p.body_text) > 500]
    candidates = [(u, s) for u, s in candidates if s]
    if len(candidates) < 2:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "not enough content pages"})
    overlaps = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            u1, s1 = candidates[i]
            u2, s2 = candidates[j]
            jac = len(s1 & s2) / len(s1 | s2)
            if jac > 0.5:
                overlaps.append({"a": u1, "b": u2, "jaccard": round(jac, 2)})
    if not overlaps:
        return Verdict("pass", 10.0, "info", 0.85, {"pages_checked": len(candidates), "duplicate_pairs": 0})
    score = max(0.0, 10.0 - len(overlaps) * 1.5)
    return Verdict(
        status_from_score(score), score,
        "major" if len(overlaps) >= 3 else "minor", 0.85,
        {"pages_checked": len(candidates), "duplicate_pairs": len(overlaps), "examples": overlaps[:5]},
        f"{len(overlaps)} page pair(s) share >50 % content. Consolidate with 301 redirects or rewrite to differentiate.",
    )


# ---------- F-2.4.1, F-2.4.3, F-2.4.4 URL structure ----------

def check_url_structure(p: ParsedHTML) -> Verdict:
    """F-2.4.1 / .3 / .4 - URL readability, slug quality, conventions."""
    parsed = urlparse(p.url)
    path = parsed.path or "/"
    issues: list[str] = []
    if len(p.url) > 200:
        issues.append(f"length={len(p.url)} (>200 chars)")
    if "_" in path:
        issues.append("uses underscores (prefer hyphens)")
    if any(c.isupper() for c in path):
        issues.append("contains uppercase")
    if parsed.query:
        issues.append(f"query params: {parsed.query[:40]}")
    # Slug-title consistency: tokens overlap
    slug_tokens = _tokens(path.replace("/", " ").replace("-", " "))
    title_tokens = _tokens(p.title or "")
    slug_consistency = (len(slug_tokens & title_tokens) / max(len(slug_tokens | title_tokens), 1)) if (slug_tokens and title_tokens) else None
    if slug_consistency is not None and slug_consistency < 0.2 and path != "/":
        issues.append(f"slug-title overlap low ({slug_consistency:.2f})")
    if not issues:
        return Verdict("pass", 10.0, "info", 0.9, {"path": path})
    score = max(0.0, 10.0 - len(issues) * 2.0)
    return Verdict(
        status_from_score(score), score,
        "minor" if len(issues) <= 2 else "major", 0.85,
        {"path": path, "issues": issues, "slug_title_overlap": slug_consistency},
        f"URL issues: {', '.join(issues)}. Use lowercase, hyphens, no params, slug derived from title.",
    )


# ---------- F-2.5.3 Image filename SEO ----------

_GENERIC_FILENAME = re.compile(r"^(img|image|photo|pic|dsc|untitled|screenshot|file|temp)[_\-]?\d*\.(jpg|jpeg|png|webp|gif|avif)$", re.IGNORECASE)


def check_image_filenames(p: ParsedHTML) -> Verdict:
    """F-2.5.3 - flag non-descriptive image filenames (IMG_2034.jpg etc)."""
    if not p.images:
        return Verdict("n_a", 0.0, "info", 1.0, {"image_count": 0})
    bad: list[str] = []
    for img in p.images:
        # Get basename from URL
        path = urlparse(img.src).path
        name = path.rsplit("/", 1)[-1]
        if _GENERIC_FILENAME.match(name) or (len(name) > 1 and name[0].isdigit() and "." in name):
            bad.append(name)
    if not bad:
        return Verdict("pass", 10.0, "info", 0.9, {"image_count": len(p.images), "bad_filenames": 0})
    ratio = len(bad) / len(p.images)
    score = max(0.0, 10.0 - ratio * 10.0)
    return Verdict(
        status_from_score(score), score,
        "minor" if ratio < 0.5 else "major", 0.85,
        {"image_count": len(p.images), "bad_filenames": len(bad), "examples": bad[:5]},
        f"{len(bad)}/{len(p.images)} images have non-descriptive filenames. Rename to keyword-rich slugs (e.g., sofa-set-lahore.jpg).",
    )


# ---------- F-2.6.3 Anchor text semantic audit ----------

_GENERIC_ANCHORS = {
    "click here", "read more", "here", "this", "more", "learn more", "see more",
    "link", "this page", "this article", "find out more", "details", "info",
}


def check_anchor_text_quality(p: ParsedHTML) -> Verdict:
    """F-2.6.3 - flag generic anchors (click here, read more, etc)."""
    internal = [link for link in p.links if link.is_internal]
    if not internal:
        return Verdict("n_a", 0.0, "info", 1.0, {"internal_link_count": 0})
    generic = [link.anchor_text for link in internal if link.anchor_text.strip().lower() in _GENERIC_ANCHORS]
    if not generic:
        return Verdict("pass", 10.0, "info", 0.85, {"internal_links": len(internal), "generic_anchors": 0})
    ratio = len(generic) / len(internal)
    score = max(0.0, 10.0 - ratio * 10.0)
    return Verdict(
        status_from_score(score), score,
        "minor" if ratio < 0.2 else "major", 0.85,
        {"internal_links": len(internal), "generic_anchors": len(generic),
         "examples": list(set(generic))[:5]},
        f"{len(generic)}/{len(internal)} internal links use generic anchors. Replace with contextual, entity-rich anchor text.",
    )


# ---------- F-4.3.1 Schema coverage audit ----------

def check_schema_coverage(p: ParsedHTML) -> Verdict:
    """F-4.3.1 - list schemas present on the page."""
    types: list[str] = []
    for block in p.schema_blocks:
        t = block.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
    if not types:
        return Verdict(
            "warn", 4.0, "major", 0.9, {"schema_count": 0, "types": []},
            "No JSON-LD schema on this page. Add at minimum WebPage + Organization, plus Article/Product/LocalBusiness as appropriate.",
        )
    unique = sorted(set(types))
    score = min(10.0, 5.0 + len(unique) * 1.0)
    return Verdict("pass", score, "info", 1.0,
                   {"schema_count": len(types), "unique_types": unique})


# ---------- F-4.4.4 AI bot crawlability ----------

_AI_BOTS = ("GPTBot", "ClaudeBot", "Claude-Web", "Google-Extended", "PerplexityBot",
            "ChatGPT-User", "OAI-SearchBot", "Applebot-Extended", "CCBot", "anthropic-ai")


def check_ai_bot_crawlability(robots_txt: str | None) -> Verdict:
    """F-4.4.4 - parse robots.txt for AI-bot blocks."""
    if not robots_txt:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no robots.txt content"})
    blocked: list[str] = []
    current_agents: list[str] = []
    in_block_for_ai = False
    for raw in robots_txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        if key.lower() == "user-agent":
            if val == "*" or any(val.lower() == b.lower() for b in _AI_BOTS):
                current_agents.append(val)
                if val != "*":
                    in_block_for_ai = True
            else:
                current_agents = []
                in_block_for_ai = False
        elif key.lower() == "disallow" and val == "/" and current_agents:
            for ua in current_agents:
                if ua.lower() in (b.lower() for b in _AI_BOTS):
                    blocked.append(ua)
    blocked = sorted(set(blocked))
    if blocked:
        return Verdict(
            "warn", 5.0, "minor", 0.9,
            {"blocked_ai_bots": blocked, "total_ai_bots_known": len(_AI_BOTS)},
            f"robots.txt blocks {len(blocked)} AI crawler(s): {', '.join(blocked)}. "
            "Confirm this is intentional - blocked bots cannot cite the site in AI answers.",
        )
    return Verdict("pass", 10.0, "info", 0.9,
                   {"blocked_ai_bots": [], "ai_bots_known": list(_AI_BOTS)})


# ---------- F-4.4.5 llms.txt presence ----------

async def check_llms_txt(site_url: str, http_client: httpx.AsyncClient | None = None) -> Verdict:
    """F-4.4.5 - check /llms.txt exists and has content."""
    url = site_url.rstrip("/") + "/llms.txt"
    own = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0, follow_redirects=True)
    try:
        resp = await client.get(url)
        if resp.status_code != 200 or not resp.text.strip():
            return Verdict(
                "warn", 4.0, "minor", 0.9, {"url": url, "status": resp.status_code},
                "No /llms.txt found. Publish one to guide AI crawlers - it is for AI what robots.txt is for search.",
            )
        body = resp.text
        return Verdict(
            "pass", 10.0, "info", 1.0,
            {"url": url, "status": 200, "bytes": len(body), "preview": body[:200]},
        )
    except httpx.TransportError as e:
        return Verdict("n_a", 0.0, "info", 0.7, {"url": url, "error": type(e).__name__})
    finally:
        if own:
            await client.aclose()


# ---------- F-5.2.4 Click-depth distribution ----------

def compute_click_depth(pages: list[CrawledPage], site_url: str) -> dict[str, int]:
    """BFS from site_url over internal links to compute click depth per URL."""
    if not pages:
        return {}
    # Build adjacency from parsed pages
    adj: dict[str, list[str]] = defaultdict(list)
    page_urls = {cp.url for cp in pages}
    for cp in pages:
        if not cp.parsed:
            continue
        for link in cp.parsed.links:
            if link.is_internal and link.href in page_urls:
                adj[cp.url].append(link.href)
    # BFS
    home_candidates = [
        cp.url for cp in pages
        if cp.url.rstrip("/") in (site_url.rstrip("/"), site_url.rstrip("/") + "/")
    ]
    start = home_candidates[0] if home_candidates else pages[0].url
    depth: dict[str, int] = {start: 0}
    queue = [start]
    while queue:
        u = queue.pop(0)
        for nxt in adj.get(u, []):
            if nxt not in depth:
                depth[nxt] = depth[u] + 1
                queue.append(nxt)
    return depth


def check_click_depth(pages: list[CrawledPage], site_url: str) -> Verdict:
    """F-5.2.4 - depth distribution + deep-page count."""
    depth = compute_click_depth(pages, site_url)
    if not depth:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no pages with links"})
    counts: Counter[int] = Counter(depth.values())
    deep = sum(c for d, c in counts.items() if d > 4)
    total = sum(counts.values())
    deep_ratio = deep / total
    distribution = {f"depth_{d}": counts[d] for d in sorted(counts)}
    if deep_ratio == 0:
        return Verdict("pass", 10.0, "info", 0.9, {"distribution": distribution, "deep_pages": 0})
    score = max(0.0, 10.0 - deep_ratio * 12.0)
    return Verdict(
        status_from_score(score), score,
        "minor" if deep_ratio < 0.2 else "major", 0.85,
        {"distribution": distribution, "deep_pages": deep, "total": total, "deep_ratio": round(deep_ratio, 2)},
        f"{deep}/{total} pages sit at click depth >4. Surface them with internal links from shallower hubs.",
    )


# ---------- F-2.2.1 H1 existence + uniqueness (per-page) ----------

def check_pagination(p: ParsedHTML) -> Verdict:
    """F-5.1.6 - presence of rel=next/prev for paginated content."""
    # We only emit a finding when there IS a paginated context.
    if not p.rel_next and not p.rel_prev:
        return Verdict("n_a", 0.0, "info", 1.0, {"rel_next": None, "rel_prev": None})
    return Verdict(
        "pass", 10.0, "info", 0.9,
        {"rel_next": p.rel_next, "rel_prev": p.rel_prev},
    )


# ---------- F-5.2.5 Footer architecture ----------

def check_footer_architecture(p: ParsedHTML) -> Verdict:
    """F-5.2.5 - footer link count + sanity."""
    n = p.footer_link_count
    if n == 0:
        return Verdict("warn", 5.0, "minor", 0.8, {"footer_links": 0},
                       "No <footer> links detected. Add a footer with secondary navigation to surface deep pages and policies.")
    if n > 60:
        return Verdict("warn", 5.0, "minor", 0.8, {"footer_links": n},
                       f"{n} footer links is excessive. Consolidate to 12-30 grouped links for crawl efficiency.")
    return Verdict("pass", 10.0, "info", 0.9, {"footer_links": n})


# ---------- F-5.4.5 HTTP version ----------

def check_http_version(cp: Any) -> Verdict:
    """F-5.4.5 - HTTP/2 or HTTP/3 expected on modern servers."""
    v = getattr(cp, "http_version", None)
    if not v:
        return Verdict("n_a", 0.0, "info", 1.0, {"http_version": None})
    if v in ("HTTP/2", "HTTP/3"):
        return Verdict("pass", 10.0, "info", 1.0, {"http_version": v})
    if v == "HTTP/1.1":
        return Verdict("warn", 6.0, "minor", 1.0, {"http_version": v},
                       "Server is on HTTP/1.1. Upgrade to HTTP/2 or HTTP/3 for faster page loads (multiplexing + header compression).")
    return Verdict("warn", 4.0, "minor", 1.0, {"http_version": v},
                   f"Server reported {v}; upgrade to HTTP/2 or HTTP/3.")


# ---------- F-7.1.1 / F-7.1.4 / F-7.1.6 EEAT signals ----------

def check_author_existence(p: ParsedHTML) -> Verdict:
    """F-7.1.1 - is there a named author on the page (byline or Person schema)?"""
    has_person_schema = any(
        (block.get("@type") == "Person" or (
            isinstance(block.get("@type"), list) and "Person" in block.get("@type", [])
        ))
        for block in p.schema_blocks
    )
    has_author_in_schema = any(
        isinstance(block.get("author"), (dict, list, str)) and block.get("author")
        for block in p.schema_blocks
    )
    if p.bylines or has_person_schema or has_author_in_schema:
        return Verdict(
            "pass", 10.0, "info", 0.85,
            {
                "bylines": p.bylines[:3],
                "has_person_schema": has_person_schema,
                "has_author_in_schema": has_author_in_schema,
            },
        )
    # On thin content pages (homepage, category) author absence is expected.
    # Only flag content-heavy pages (>500 words) as missing author.
    if p.word_count < 500:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "not a content page (<500 words)"})
    return Verdict(
        "warn", 4.0, "major", 0.8,
        {"word_count": p.word_count, "bylines": []},
        "Content page has no detectable author. Add a byline + Person schema with credentials for E-E-A-T.",
    )


def check_person_schema_completeness(p: ParsedHTML) -> Verdict:
    """F-7.1.2 / F-7.1.4 - Person schema with bio + sameAs + jobTitle."""
    persons = [
        b for b in p.schema_blocks
        if (b.get("@type") == "Person" or (isinstance(b.get("@type"), list) and "Person" in b.get("@type", [])))
    ]
    if not persons:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no Person schema on page"})
    # Score the first Person block (most pages have one author).
    person = persons[0]
    required = ("name", "url")
    boosters = ("jobTitle", "description", "sameAs", "image", "knowsAbout", "alumniOf")
    has_required = sum(1 for k in required if person.get(k))
    has_boost = sum(1 for k in boosters if person.get(k))
    score = min(10.0, has_required * 3.0 + has_boost * 1.0)
    missing = [k for k in required if not person.get(k)]
    if missing:
        return Verdict(
            "warn", score, "major", 0.9,
            {"name": person.get("name"), "missing_required": missing, "has_boosters": has_boost},
            f"Person schema missing required fields: {missing}. Add at minimum name + url.",
        )
    return Verdict(
        "pass" if score >= 7 else "warn", score, "minor" if score < 7 else "info", 0.9,
        {"name": person.get("name"), "boosters_present": has_boost, "total_boosters": len(boosters)},
        None if score >= 7 else "Strengthen Person schema with jobTitle, description, sameAs (LinkedIn / Twitter), and image.",
    )


def check_about_contact_pages(pages: list[ParsedHTML]) -> Verdict:
    """F-7.1.10 - About and Contact pages are basic trust signals."""
    if not pages:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no pages"})
    about_linked = any(p.has_about_page_link for p in pages)
    contact_linked = any(p.has_contact_page_link for p in pages)
    # Also check if any crawled URL itself looks like an about/contact page
    urls = [p.url.lower() for p in pages]
    has_about_url = any("/about" in u for u in urls)
    has_contact_url = any("/contact" in u for u in urls)
    missing: list[str] = []
    if not (about_linked or has_about_url):
        missing.append("About page")
    if not (contact_linked or has_contact_url):
        missing.append("Contact page")
    if not missing:
        return Verdict("pass", 10.0, "info", 0.95,
                       {"about_linked": about_linked, "contact_linked": contact_linked,
                        "about_url_present": has_about_url, "contact_url_present": has_contact_url})
    sev = "major" if len(missing) == 2 else "minor"
    score = 4.0 if len(missing) == 2 else 7.0
    return Verdict(
        "warn", score, sev, 0.9,
        {"missing": missing, "about_linked": about_linked, "contact_linked": contact_linked},
        f"Site lacks visible link(s) to: {', '.join(missing)}. Both are baseline trust + E-E-A-T signals (Quality Rater Guidelines).",
    )


# ---------- F-5.3 UX / Core Web Vitals from PSI -----------

_CWV_BUDGETS = {
    "largest_contentful_paint": (2500.0, 4000.0, "ms"),         # LCP good / needs / poor
    "cumulative_layout_shift": (0.10, 0.25, ""),                # CLS unitless
    "interaction_to_next_paint": (200.0, 500.0, "ms"),          # INP
    "first_contentful_paint": (1800.0, 3000.0, "ms"),           # FCP
    "experimental_time_to_first_byte": (800.0, 1800.0, "ms"),   # TTFB
    "server_response_time": (200.0, 600.0, "ms"),               # lab TTFB
    "first_input_delay": (100.0, 300.0, "ms"),                  # FID (legacy)
}


def _cwv_verdict(metric_id: str, value: float | None, *, unit_override: str | None = None) -> Verdict:
    if value is None:
        return Verdict("n_a", 0.0, "info", 0.9, {"metric": metric_id, "value": None})
    budgets = _CWV_BUDGETS.get(metric_id)
    if not budgets:
        return Verdict("n_a", 0.0, "info", 0.7, {"metric": metric_id, "value": value})
    good, needs, unit = budgets
    unit = unit_override or unit
    if value <= good:
        return Verdict("pass", 10.0, "info", 0.95,
                       {"metric": metric_id, "value": value, "unit": unit, "band": "good"})
    if value <= needs:
        return Verdict("warn", 6.0, "minor", 0.9,
                       {"metric": metric_id, "value": value, "unit": unit, "band": "needs_improvement"},
                       f"{metric_id} = {value:g}{unit} (needs improvement). Target <= {good:g}{unit}.")
    return Verdict("fail", 3.0, "major", 0.9,
                   {"metric": metric_id, "value": value, "unit": unit, "band": "poor"},
                   f"{metric_id} = {value:g}{unit} (poor). Target <= {good:g}{unit}.")


def iter_cwv_findings(psi_result: Any) -> Iterable[tuple[str, str, Verdict]]:
    """Yield per-metric findings from a PSI result. Tries field metrics first,
    falls back to lab metrics. Maps to:
      TECH-070 LCP, TECH-071 CLS, TECH-072 INP, TECH-073 TTFB, TECH-074 FCP
    """
    by_id_field: dict[str, float] = {}
    for m in getattr(psi_result, "field_metrics", []) or []:
        mid = (m.name or "").lower()
        if mid and m.percentile is not None:
            by_id_field[mid] = float(m.percentile)
    by_id_lab: dict[str, float] = {}
    for m in getattr(psi_result, "lab_metrics", []) or []:
        mid = (m.name or "").lower()
        if mid and m.value is not None:
            by_id_lab[mid] = float(m.value)

    def _pick(metric_id: str) -> float | None:
        return by_id_field.get(metric_id, by_id_lab.get(metric_id))

    yield ("TECH-070", "B2", _cwv_verdict("largest_contentful_paint", _pick("largest_contentful_paint")))
    yield ("TECH-071", "B2", _cwv_verdict("cumulative_layout_shift", _pick("cumulative_layout_shift")))
    # INP may live under interaction_to_next_paint OR experimental_interaction_to_next_paint
    inp = _pick("interaction_to_next_paint") or by_id_field.get("experimental_interaction_to_next_paint")
    yield ("TECH-072", "B2", _cwv_verdict("interaction_to_next_paint", inp))
    ttfb = (
        by_id_field.get("experimental_time_to_first_byte")
        or by_id_lab.get("server_response_time")
    )
    yield ("TECH-073", "B2", _cwv_verdict("experimental_time_to_first_byte", ttfb))
    yield ("TECH-074", "B2", _cwv_verdict("first_contentful_paint", _pick("first_contentful_paint")))


def check_lighthouse_category(name: str, score: float | None, *, severity_below: str = "major") -> Verdict:
    """Generic Lighthouse 0-100 category -> verdict (a11y, best-practices, seo)."""
    if score is None:
        return Verdict("n_a", 0.0, "info", 1.0, {"category": name})
    s10 = score / 10.0
    band = "good" if score >= 90 else "needs_improvement" if score >= 50 else "poor"
    if score >= 90:
        return Verdict("pass", s10, "info", 0.95, {"category": name, "lighthouse_score": score, "band": band})
    return Verdict(
        "fail" if score < 50 else "warn",
        s10,
        severity_below if score < 50 else "minor",
        0.9,
        {"category": name, "lighthouse_score": score, "band": band},
        f"Lighthouse {name} score is {score:.0f}/100 ({band}). Open the PSI report for opportunities.",
    )


def iter_psi_quality_findings(psi_result: Any) -> Iterable[tuple[str, str, Verdict]]:
    """Yield findings for Lighthouse a11y / best-practices / seo scores."""
    scores = getattr(psi_result, "lighthouse_scores", {}) or {}
    yield ("ON-105", "A3", check_lighthouse_category("accessibility", scores.get("accessibility")))
    yield ("TECH-082", "B5", check_lighthouse_category("best-practices", scores.get("best-practices")))
    yield ("ON-106", "A3", check_lighthouse_category("seo", scores.get("seo"), severity_below="minor"))


# ---------- Aggregator ----------

def iter_per_page_extras(p: ParsedHTML) -> Iterable[tuple[str, str, Verdict]]:
    """Yield (check_id, owner, verdict) for per-page extras.

    Only checks that fill a genuine GAP (no overlap with onpage.py's emitted
    check_ids) live here. ON-097 URL hygiene - long URLs, underscores,
    uppercase, query params, slug-title mismatch - is the Semrush "URL
    structure" family and is not emitted anywhere else, so it is activated
    here. Owner A3 (headings / meta / URL structure analyst).
    """
    yield ("ON-097", "A3", check_url_structure(p))
