"""On-page analyzers used by /audit-quick.

Maps to checklist YAML IDs. Phase 1A ships the deterministic core for ~25
checks; the rest fill in as Team A agents pick them up.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import mean
from typing import Iterable

from audit_engine.analyzers.common import Verdict, length_score, status_from_score
from audit_engine.crawlers.basic import CrawledPage
from audit_engine.parsers.html import ParsedHTML
from audit_engine.parsers.jsonld import validate_all


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with", "by", "at", "is", "are", "be",
    "this", "that", "these", "those", "from", "as", "it", "its", "into", "your", "our", "their",
}
_POWER_WORDS = {
    "best", "top", "proven", "ultimate", "guide", "checklist", "tips", "review", "vs", "compare",
    "easy", "fast", "simple", "free", "new", "2024", "2025", "2026",
}
_CTA_VERBS = {
    "get", "buy", "book", "call", "contact", "schedule", "request", "download", "start", "try", "learn",
    "discover", "compare",
}
_TRANSITION_STARTS = {
    "however", "therefore", "moreover", "additionally", "also", "next", "then", "finally", "in", "first",
}

_SENT_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"[A-Za-z]+")
_VOWEL_RUN = re.compile(r"[aeiouy]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


def _primary_phrase(p: ParsedHTML) -> str:
    base = (p.h1s[0] if p.h1s else p.title) or ""
    toks = _tokens(base)
    if not toks:
        return ""
    return " ".join(toks[:3])


def _primary_tokens(p: ParsedHTML) -> set[str]:
    phrase = _primary_phrase(p)
    return set(_tokens(phrase))


def _top_terms(text: str, n: int = 12) -> list[str]:
    toks = _tokens(text)
    if not toks:
        return []
    counts = Counter(toks)
    return [t for t, _ in counts.most_common(n)]


def _sentence_stats(text: str) -> tuple[int, float]:
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return (0, 0.0)
    word_counts = [len(_tokens(s)) for s in sentences]
    return (len(sentences), mean(word_counts) if word_counts else 0.0)


def _syllable_count(word: str) -> int:
    word = word.lower().rstrip("e")
    runs = _VOWEL_RUN.findall(word)
    return max(len(runs), 1)


def check_readability(p: ParsedHTML) -> Verdict:
    """ON-051 Content readability analysis (Flesch Reading Ease)."""
    text = (p.body_text or "")[:20000]
    if not text or len(text) < 200:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "too little text"})
    sentences = max(len([s for s in _SENT_RE.split(text) if s.strip()]), 1)
    words = _WORD_RE.findall(text)
    if len(words) < 50:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "too few words"})
    syllables = sum(_syllable_count(w) for w in words)
    fre = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    fre = max(0.0, min(100.0, fre))
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


def check_title_tag(p: ParsedHTML) -> Verdict:
    """ON-034 Title tag optimization (deterministic core)."""
    title = (p.title or "").strip()
    if not title:
        return Verdict(
            status="fail",
            score=0.0,
            severity="critical",
            confidence=1.0,
            evidence={"title": None, "length": 0},
            remediation="Add a <title> tag with the primary keyword in the first 60 characters.",
        )
    score = length_score(p.title_length, ideal_min=30, ideal_max=60, hard_max=75)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major" if score < 6 else "minor",
        confidence=0.9,
        evidence={"title": title, "length": p.title_length, "ideal_range": "30-60"},
        remediation=(
            None
            if score >= 9
            else f"Title is {p.title_length} chars; aim for 30-60 with primary keyword early."
        ),
    )


def check_title_uniqueness(pages: list[ParsedHTML]) -> dict[str, Verdict]:
    """ON-036 Title uniqueness check (site-wide)."""
    title_counts = Counter((p.title or "").strip() for p in pages if p.title)
    out: dict[str, Verdict] = {}
    for p in pages:
        title = (p.title or "").strip()
        if not title:
            out[p.url] = Verdict(
                "fail", 0.0, "major", 1.0, {"reason": "missing title"}, "Add a <title>."
            )
            continue
        dup_count = title_counts[title]
        if dup_count > 1:
            out[p.url] = Verdict(
                status="fail",
                score=4.0,
                severity="major",
                confidence=1.0,
                evidence={"title": title, "duplicate_count": dup_count},
                remediation=f"Title '{title}' is shared by {dup_count} pages; make each title unique.",
            )
        else:
            out[p.url] = Verdict(
                status="pass",
                score=10.0,
                severity="info",
                confidence=1.0,
                evidence={"title": title, "duplicate_count": 1},
            )
    return out


def check_meta_description(p: ParsedHTML) -> Verdict:
    """ON-038 Meta description optimization."""
    md = (p.meta_description or "").strip()
    if not md:
        return Verdict(
            status="fail",
            score=2.0,
            severity="major",
            confidence=1.0,
            evidence={"meta_description": None},
            remediation="Add a 120-158 character meta description summarizing the page intent.",
        )
    score = length_score(p.meta_description_length, ideal_min=120, ideal_max=158, hard_max=200)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major" if score < 6 else "minor",
        confidence=0.9,
        evidence={"length": p.meta_description_length, "ideal_range": "120-158"},
        remediation=(None if score >= 9 else f"Meta description is {p.meta_description_length} chars."),
    )


def check_h1_optimization(p: ParsedHTML) -> Verdict:
    """ON-041 H1 optimization + ON-042 multiple H1 detection (combined)."""
    if not p.h1s:
        return Verdict(
            status="fail",
            score=0.0,
            severity="critical",
            confidence=1.0,
            evidence={"h1_count": 0},
            remediation="Add exactly one H1 describing the page topic.",
        )
    if len(p.h1s) > 1:
        return Verdict(
            status="fail",
            score=4.0,
            severity="major",
            confidence=1.0,
            evidence={"h1_count": len(p.h1s), "h1s": p.h1s[:5]},
            remediation=f"Page has {len(p.h1s)} H1s; keep only one.",
        )
    return Verdict(
        status="pass",
        score=10.0,
        severity="info",
        confidence=1.0,
        evidence={"h1_count": 1, "h1": p.h1s[0]},
    )


def check_heading_hierarchy(p: ParsedHTML) -> Verdict:
    """ON-043 Heading hierarchy analysis."""
    if not p.headings:
        return Verdict(
            "fail", 2.0, "major", 0.8,
            {"reason": "no headings detected"},
            "Add semantic headings (H1, H2) to structure the page.",
        )
    last_level = 0
    skips: list[str] = []
    for h in p.headings:
        if last_level and h.level > last_level + 1:
            skips.append(f"H{last_level}->H{h.level}: '{h.text[:80]}'")
        last_level = h.level
    if skips:
        return Verdict(
            "warn", 6.0, "minor", 0.9,
            {"skip_count": len(skips), "examples": skips[:3]},
            "Avoid skipping heading levels; keep H1->H2->H3 progression.",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"headings": len(p.headings)})


def check_title_ctr(p: ParsedHTML) -> Verdict:
    """ON-035 Title CTR optimization (heuristic)."""
    title = (p.title or "").strip()
    if not title:
        return Verdict("fail", 0.0, "major", 1.0, {"title": None}, "Add a descriptive title tag.")
    has_number = any(ch.isdigit() for ch in title)
    has_power = any(w in _POWER_WORDS for w in _tokens(title))
    score = 10.0 if (has_number or has_power) else 7.0
    if len(title) < 25 or len(title) > 70:
        score = min(score, 6.0)
    status = status_from_score(score)
    remediation = None
    if score < 9:
        remediation = "Add a number or strong value word (best, guide, checklist) while keeping length 30-60 chars."
    return Verdict(status, score, "minor" if score >= 6 else "major", 0.8,
                   {"title": title, "has_number": has_number, "has_power_word": has_power}, remediation)


def check_title_keyword_placement(p: ParsedHTML) -> Verdict:
    """ON-037 Title keyword placement."""
    title = (p.title or "").strip()
    if not title:
        return Verdict("fail", 0.0, "major", 1.0, {"title": None}, "Add a title tag with the primary keyword early.")
    primary = _primary_phrase(p)
    if not primary:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no primary keyword"})
    first_words = " ".join(title.split()[:3]).lower()
    if primary in first_words:
        return Verdict("pass", 10.0, "info", 0.9, {"primary": primary, "placement": "early"})
    return Verdict("warn", 6.0, "minor", 0.8,
                   {"primary": primary, "placement": "late"},
                   "Move the primary keyword into the first 3 words of the title.")


def check_meta_ctr(p: ParsedHTML) -> Verdict:
    """ON-039 Meta description CTR analysis (heuristic)."""
    md = (p.meta_description or "").strip()
    if not md:
        return Verdict("fail", 2.0, "major", 1.0, {"meta_description": None},
                       "Add a meta description with a clear benefit and action verb.")
    has_number = any(ch.isdigit() for ch in md)
    tokens = _tokens(md)
    has_cta = any(t in _CTA_VERBS for t in tokens)
    score = 10.0 if (has_number or has_cta) else 7.0
    if len(md) < 120 or len(md) > 180:
        score = min(score, 6.0)
    return Verdict(status_from_score(score), score, "minor" if score >= 6 else "major", 0.8,
                   {"has_cta": has_cta, "has_number": has_number, "length": len(md)},
                   "Add a number or action verb to improve CTR." if score < 9 else None)


def check_multiple_h1(p: ParsedHTML) -> Verdict:
    """ON-042 Multiple H1 detection."""
    if not p.h1s:
        return Verdict("fail", 0.0, "major", 1.0, {"h1_count": 0}, "Add exactly one H1 tag.")
    if len(p.h1s) > 1:
        return Verdict("fail", 4.0, "major", 1.0, {"h1_count": len(p.h1s), "h1s": p.h1s[:5]},
                       "Keep a single H1 to avoid topic ambiguity.")
    return Verdict("pass", 10.0, "info", 1.0, {"h1_count": 1})


def check_heading_semantics(p: ParsedHTML) -> Verdict:
    """ON-044 Semantic heading optimization."""
    if not p.headings:
        return Verdict("fail", 3.0, "major", 0.9, {"headings": 0}, "Add H2/H3 headings for key subtopics.")
    body_terms = set(_top_terms(p.body_text or "", n=12))
    heading_terms = set(_tokens(" ".join(h.text for h in p.headings)))
    if not body_terms:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no body terms"})
    coverage = len(body_terms & heading_terms) / max(len(body_terms), 1)
    if coverage >= 0.5:
        return Verdict("pass", 10.0, "info", 0.85, {"coverage": round(coverage, 2)})
    if coverage >= 0.25:
        return Verdict("warn", 6.0, "minor", 0.8, {"coverage": round(coverage, 2)},
                       "Align H2/H3 headings to cover the page's core entities and attributes.")
    return Verdict("fail", 3.0, "major", 0.85, {"coverage": round(coverage, 2)},
                   "Headings do not reflect core topics. Rewrite H2/H3 to match key entities and intents.")


def check_heading_questions(p: ParsedHTML) -> Verdict:
    """ON-045 Question based heading detection."""
    headings = [h.text for h in p.headings if h.level in (2, 3)]
    if not headings:
        return Verdict("n_a", 0.0, "info", 1.0, {"heading_count": 0})
    questions = sum(1 for h in headings if h.endswith("?") or re.match(r"^(what|why|how|when|where|who|which)\b", h.lower()))
    ratio = questions / len(headings)
    if ratio >= 0.3:
        return Verdict("pass", 10.0, "info", 0.9, {"heading_count": len(headings), "question_count": questions})
    return Verdict("warn", 6.0, "minor", 0.8, {"heading_count": len(headings), "question_count": questions},
                   "Convert 2-3 headings into question form to improve PAA and AI Overview eligibility.")


def check_featured_snippet(p: ParsedHTML) -> Verdict:
    """ON-046 Featured snippet optimization."""
    snippet_paras = [w for w in p.paragraph_word_counts if 18 <= w <= 45]
    has_list = p.list_count + p.ordered_list_count > 0
    has_table = p.table_count > 0
    score = 4.0
    if snippet_paras:
        score += 3.0
    if has_list:
        score += 2.0
    if has_table:
        score += 1.0
    score = min(score, 10.0)
    status = status_from_score(score)
    remediation = None
    if score < 7:
        remediation = "Add a 30-45 word definition paragraph and a list/table for snippet eligibility."
    return Verdict(status, score, "minor" if score >= 6 else "major", 0.8,
                   {"short_paragraphs": len(snippet_paras), "lists": p.list_count + p.ordered_list_count, "tables": p.table_count},
                   remediation)


def check_passage_ranking(p: ParsedHTML) -> Verdict:
    """ON-047 Passage ranking optimization."""
    passages = [w for w in p.paragraph_word_counts if 40 <= w <= 90]
    if not p.paragraph_word_counts:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no paragraphs"})
    if len(passages) >= 2:
        return Verdict("pass", 10.0, "info", 0.85, {"passage_count": len(passages)})
    return Verdict("warn", 6.0, "minor", 0.8, {"passage_count": len(passages)},
                   "Add 1-2 mid-length passages (40-90 words) focused on a single subtopic.")


def check_ai_overview(p: ParsedHTML) -> Verdict:
    """ON-048 AI overview optimization (heuristic)."""
    q = check_heading_questions(p)
    snippet = check_featured_snippet(p)
    direct = check_direct_answer(p)
    score = round((q.score + snippet.score + direct.score) / 3.0, 1)
    return Verdict(status_from_score(score), score, "minor" if score >= 6 else "major", 0.75,
                   {"question_headings": q.evidence.get("question_count"),
                    "snippet_blocks": snippet.evidence.get("short_paragraphs"),
                    "direct_answer": direct.status})


def check_direct_answer(p: ParsedHTML) -> Verdict:
    """ON-049 Direct answer optimization."""
    primary = _primary_phrase(p)
    for para in p.paragraphs[:5]:
        text = para.strip()
        words = len(_tokens(text))
        if words <= 45 and primary and text.lower().startswith(primary):
            return Verdict("pass", 10.0, "info", 0.85, {"example": text[:120]})
    return Verdict("warn", 6.0, "minor", 0.8, {"primary": primary},
                   "Add a direct 1-2 sentence answer immediately after a question heading.")


def check_faq_optimization(p: ParsedHTML) -> Verdict:
    """ON-050 FAQ optimization."""
    has_faq_schema = any(
        (b.get("@type") == "FAQPage" or (isinstance(b.get("@type"), list) and "FAQPage" in b.get("@type", [])))
        for b in p.schema_blocks
    )
    q_headings = [h for h in p.headings if h.text.strip().endswith("?")]
    if has_faq_schema or q_headings:
        return Verdict("pass", 10.0, "info", 0.85,
                       {"faq_schema": has_faq_schema, "question_headings": len(q_headings)})
    return Verdict("warn", 6.0, "minor", 0.8, {"faq_schema": False, "question_headings": 0},
                   "Add an FAQ section with 3-5 Q&A pairs and FAQPage schema.")


def check_paragraph_length(p: ParsedHTML) -> Verdict:
    """ON-053 Paragraph length analysis."""
    if not p.paragraph_word_counts:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no paragraphs"})
    avg_len = mean(p.paragraph_word_counts)
    if 40 <= avg_len <= 120:
        return Verdict("pass", 10.0, "info", 0.85, {"avg_words": round(avg_len, 1)})
    severity = "minor" if avg_len <= 150 else "major"
    return Verdict("warn", 6.0, severity, 0.8, {"avg_words": round(avg_len, 1)},
                   "Keep paragraphs in the 40-120 word range for readability.")


def check_sentence_complexity(p: ParsedHTML) -> Verdict:
    """ON-054 Sentence complexity analysis."""
    count, avg_words = _sentence_stats(p.body_text or "")
    if count == 0:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no sentences"})
    if avg_words <= 20:
        return Verdict("pass", 10.0, "info", 0.85, {"avg_words": round(avg_words, 1)})
    return Verdict("warn", 6.0, "minor", 0.8, {"avg_words": round(avg_words, 1)},
                   "Shorten sentences to improve readability and extractability.")


def check_scannability(p: ParsedHTML) -> Verdict:
    """ON-055 Content scannability analysis."""
    headings = len(p.headings)
    lists = p.list_count + p.ordered_list_count
    short_paras = sum(1 for w in p.paragraph_word_counts if w <= 80)
    total_paras = max(len(p.paragraph_word_counts), 1)
    scan_ratio = (short_paras / total_paras) + (0.1 * headings) + (0.2 * lists)
    score = min(10.0, round(scan_ratio * 5.0, 1))
    if score >= 7:
        return Verdict("pass", score, "info", 0.85, {"headings": headings, "lists": lists})
    return Verdict("warn", score, "minor", 0.8, {"headings": headings, "lists": lists},
                   "Improve scannability with more subheadings, short paragraphs, and lists.")


def check_intro_optimization(p: ParsedHTML) -> Verdict:
    """ON-056 Intro optimization."""
    if not p.paragraphs:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no intro"})
    intro = p.paragraphs[0]
    words = len(_tokens(intro))
    primary = _primary_tokens(p)
    has_primary = any(t in intro.lower() for t in primary) if primary else False
    if 40 <= words <= 90 and has_primary:
        return Verdict("pass", 10.0, "info", 0.85, {"intro_words": words, "has_primary": True})
    return Verdict("warn", 6.0, "minor", 0.8, {"intro_words": words, "has_primary": has_primary},
                   "Make the intro 40-90 words and include the primary entity or keyword.")


def check_anchor_text_optimization(p: ParsedHTML) -> Verdict:
    """ON-058 Anchor text optimization."""
    internal = [link for link in p.links if link.is_internal]
    if not internal:
        return Verdict("n_a", 0.0, "info", 1.0, {"internal_link_count": 0})
    generic = [link.anchor_text for link in internal if link.anchor_text.strip().lower() in {
        "click here", "read more", "here", "this", "more", "learn more", "see more",
        "link", "this page", "this article", "find out more", "details", "info",
    }]
    if not generic:
        return Verdict("pass", 10.0, "info", 0.85, {"internal_links": len(internal), "generic_anchors": 0})
    ratio = len(generic) / len(internal)
    score = max(0.0, 10.0 - ratio * 10.0)
    return Verdict(status_from_score(score), score, "minor" if ratio < 0.2 else "major", 0.85,
                   {"internal_links": len(internal), "generic_anchors": len(generic)},
                   "Replace generic anchors with contextual, entity-rich text.")


def check_external_link_quality(p: ParsedHTML) -> Verdict:
    """ON-065 External link quality analysis (heuristic)."""
    external = [link for link in p.links if not link.is_internal]
    if not external:
        return Verdict("n_a", 0.0, "info", 0.7, {"external_links": 0})
    insecure = [l for l in external if l.href.startswith("http://")]
    score = 10.0 if not insecure else max(4.0, 10.0 - len(insecure) * 2.0)
    status = status_from_score(score)
    remediation = None
    if insecure:
        remediation = "Update external links to HTTPS where possible."
    return Verdict(status, score, "minor" if score >= 6 else "major", 0.8,
                   {"external_links": len(external), "http_links": len(insecure)}, remediation)


def check_outbound_authority(p: ParsedHTML) -> Verdict:
    """ON-066 Outbound authority link analysis (heuristic)."""
    external = [link.href for link in p.links if not link.is_internal]
    if not external:
        return Verdict("n_a", 0.0, "info", 0.7, {"external_links": 0})
    authority = [u for u in external if ".gov" in u or ".edu" in u]
    if authority:
        return Verdict("pass", 10.0, "info", 0.8, {"authority_links": len(authority)})
    return Verdict("warn", 6.0, "minor", 0.75, {"authority_links": 0},
                   "Cite at least one authoritative source (.gov/.edu) where relevant.")


def check_image_filename(p: ParsedHTML) -> Verdict:
    """ON-069 Image filename optimization."""
    if not p.images:
        return Verdict("n_a", 0.0, "info", 1.0, {"image_count": 0})
    bad: list[str] = []
    for img in p.images:
        name = img.src.rsplit("/", 1)[-1]
        if re.match(r"^(img|image|photo|pic|dsc|untitled|screenshot|file|temp)[_\-]?\d*\.(jpg|jpeg|png|webp|gif|avif)$", name, re.IGNORECASE):
            bad.append(name)
    if not bad:
        return Verdict("pass", 10.0, "info", 0.9, {"image_count": len(p.images), "bad_filenames": 0})
    ratio = len(bad) / len(p.images)
    score = max(0.0, 10.0 - ratio * 10.0)
    return Verdict(status_from_score(score), score, "minor" if ratio < 0.5 else "major", 0.85,
                   {"image_count": len(p.images), "bad_filenames": len(bad), "examples": bad[:5]},
                   "Rename images to descriptive, keyword-rich filenames.")


def check_webp_usage(p: ParsedHTML) -> Verdict:
    """ON-071 WebP image usage check."""
    if not p.images:
        return Verdict("n_a", 0.0, "info", 1.0, {"image_count": 0})
    has_webp = any(img.src.lower().endswith((".webp", ".avif")) for img in p.images)
    if has_webp:
        return Verdict("pass", 10.0, "info", 0.9, {"webp_or_avif": True})
    return Verdict("warn", 6.0, "minor", 0.8, {"webp_or_avif": False},
                   "Serve images as WebP or AVIF for better performance.")


def check_lazy_loading(p: ParsedHTML) -> Verdict:
    """ON-072 Lazy loading optimization."""
    if not p.images:
        return Verdict("n_a", 0.0, "info", 1.0, {"image_count": 0})
    lazy = sum(1 for img in p.images if img.is_lazy)
    ratio = lazy / len(p.images)
    score = round(ratio * 10, 1)
    if ratio >= 0.6:
        return Verdict("pass", 10.0, "info", 0.9, {"lazy_ratio": round(ratio, 2)})
    return Verdict(status_from_score(score), score, "minor", 0.8,
                   {"lazy_ratio": round(ratio, 2)}, "Enable loading=lazy for non-critical images.")


def check_faq_schema(p: ParsedHTML) -> Verdict:
    """ON-074 FAQ schema optimization."""
    has_faq = any(
        (b.get("@type") == "FAQPage" or (isinstance(b.get("@type"), list) and "FAQPage" in b.get("@type", [])))
        for b in p.schema_blocks
    )
    if has_faq:
        return Verdict("pass", 10.0, "info", 0.9, {"faq_schema": True})
    return Verdict("warn", 6.0, "minor", 0.8, {"faq_schema": False},
                   "Add FAQPage schema to Q&A sections.")


def check_article_schema(p: ParsedHTML) -> Verdict:
    """ON-075 Article schema validation."""
    has_article = any(
        (b.get("@type") in {"Article", "NewsArticle", "BlogPosting"} or (
            isinstance(b.get("@type"), list) and any(t in {"Article", "NewsArticle", "BlogPosting"} for t in b.get("@type", []))
        ))
        for b in p.schema_blocks
    )
    if has_article:
        return Verdict("pass", 10.0, "info", 0.9, {"article_schema": True})
    if p.word_count >= 500:
        return Verdict("warn", 6.0, "minor", 0.8, {"article_schema": False},
                       "Add Article or BlogPosting schema for content pages.")
    return Verdict("n_a", 0.0, "info", 0.7, {"article_schema": False})


def check_service_schema(p: ParsedHTML) -> Verdict:
    """ON-076 Service schema optimization."""
    has_service = any(
        (b.get("@type") == "Service" or (isinstance(b.get("@type"), list) and "Service" in b.get("@type", [])))
        for b in p.schema_blocks
    )
    if has_service:
        return Verdict("pass", 10.0, "info", 0.9, {"service_schema": True})
    return Verdict("warn", 6.0, "minor", 0.8, {"service_schema": False},
                   "Add Service schema on core service pages.")


def check_breadcrumb_schema(p: ParsedHTML) -> Verdict:
    """ON-077 Breadcrumb schema validation."""
    has_breadcrumb = any(
        (b.get("@type") == "BreadcrumbList" or (isinstance(b.get("@type"), list) and "BreadcrumbList" in b.get("@type", [])))
        for b in p.schema_blocks
    )
    if has_breadcrumb or p.has_breadcrumb_nav:
        return Verdict("pass", 10.0, "info", 0.9, {"breadcrumb_schema": has_breadcrumb})
    return Verdict("warn", 6.0, "minor", 0.8, {"breadcrumb_schema": False},
                   "Add BreadcrumbList schema and visible breadcrumbs on content pages.")


def check_rich_result_eligibility(p: ParsedHTML) -> Verdict:
    """ON-078 Rich result eligibility analysis."""
    results = validate_all(p.schema_blocks)
    eligible = sum(1 for r in results if r.rich_result_eligible)
    if eligible > 0:
        return Verdict("pass", 10.0, "info", 0.9, {"eligible_blocks": eligible})
    if p.schema_blocks:
        return Verdict("warn", 6.0, "minor", 0.8, {"eligible_blocks": 0},
                       "Add required fields to schema to unlock rich results.")
    return Verdict("warn", 4.0, "major", 0.9, {"eligible_blocks": 0},
                   "Implement structured data for rich result eligibility.")


def check_content_depth(p: ParsedHTML) -> Verdict:
    """ON-022 Content depth analysis."""
    wc = p.word_count
    heading_count = len(p.headings)
    if wc >= 900 and heading_count >= 6:
        return Verdict("pass", 10.0, "info", 0.85, {"word_count": wc, "headings": heading_count})
    score = max(0.0, min(10.0, (wc / 900) * 7.0 + (heading_count / 6) * 3.0))
    return Verdict(status_from_score(score), round(score, 1), "major", 0.8,
                   {"word_count": wc, "headings": heading_count},
                   "Expand depth with more subtopics and evidence to reach 900+ words.")


def check_primary_keyword_optimization(p: ParsedHTML) -> Verdict:
    """ON-006 Primary keyword optimization."""
    primary = _primary_phrase(p)
    if not primary:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no primary keyword"})
    targets = {
        "title": (p.title or "").lower(),
        "h1": (p.h1s[0] if p.h1s else "").lower(),
        "meta": (p.meta_description or "").lower(),
        "url": p.url.lower(),
    }
    hits = sum(1 for v in targets.values() if primary in v)
    score = min(10.0, hits * 2.5)
    return Verdict(status_from_score(score), score, "major" if score < 6 else "minor", 0.8,
                   {"primary": primary, "hits": hits},
                   "Include the primary keyword in title, H1, meta description, and URL slug.")


def check_secondary_keywords(p: ParsedHTML) -> Verdict:
    """ON-007 Secondary keyword optimization."""
    terms = _top_terms(p.body_text or "", n=8)
    primary = _primary_tokens(p)
    secondary = [t for t in terms if t not in primary]
    if not secondary:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no secondary terms"})
    heading_text = " ".join(h.text for h in p.headings).lower()
    covered = sum(1 for t in secondary if t in heading_text)
    ratio = covered / len(secondary)
    score = round(ratio * 10, 1)
    return Verdict(status_from_score(score), score, "minor" if score >= 6 else "major", 0.8,
                   {"secondary_terms": secondary[:6], "covered": covered},
                   "Use secondary terms in H2/H3 headings and supporting paragraphs.")


def check_keyword_stuffing(p: ParsedHTML) -> Verdict:
    """ON-011 Keyword stuffing detection."""
    terms = _tokens(p.body_text or "")
    if len(terms) < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too few tokens"})
    counts = Counter(terms)
    top_term, top_count = counts.most_common(1)[0]
    ratio = top_count / len(terms)
    if ratio < 0.03:
        return Verdict("pass", 10.0, "info", 0.85, {"top_term": top_term, "ratio": round(ratio, 3)})
    if ratio < 0.06:
        return Verdict("warn", 6.0, "minor", 0.8, {"top_term": top_term, "ratio": round(ratio, 3)},
                       "Reduce repetition of the primary keyword.")
    return Verdict("fail", 3.0, "major", 0.85, {"top_term": top_term, "ratio": round(ratio, 3)},
                   "Keyword repetition is high. Rewrite to improve natural phrasing.")


def check_related_entities(p: ParsedHTML) -> Verdict:
    """ON-014 Related entities optimization (heuristic)."""
    text = p.body_text or ""
    entities = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text)
    unique = {e for e in entities if len(e.split()) <= 3}
    if len(unique) >= 8:
        return Verdict("pass", 10.0, "info", 0.75, {"entity_count": len(unique)})
    return Verdict("warn", 6.0, "minor", 0.7, {"entity_count": len(unique)},
                   "Add relevant entities, tools, and attributes to strengthen semantic context.")


def check_expertise_signals(p: ParsedHTML) -> Verdict:
    """ON-027 Expertise signal detection (heuristic)."""
    numbers = sum(1 for ch in (p.body_text or "") if ch.isdigit())
    external = [link.href for link in p.links if not link.is_internal]
    citations = sum(1 for u in external if ".gov" in u or ".edu" in u or "doi.org" in u)
    score = min(10.0, numbers * 0.2 + citations * 2.0)
    if score >= 7:
        return Verdict("pass", score, "info", 0.75, {"numbers": numbers, "citations": citations})
    return Verdict("warn", max(4.0, score), "minor", 0.7, {"numbers": numbers, "citations": citations},
                   "Add data points, citations, or research references to demonstrate expertise.")


def check_trust_signals(p: ParsedHTML) -> Verdict:
    """ON-028 Trust signal analysis."""
    anchors = [l.anchor_text.lower() for l in p.links if l.anchor_text]
    has_privacy = any("privacy" in a for a in anchors)
    has_terms = any("terms" in a or "refund" in a or "returns" in a for a in anchors)
    has_contact = p.has_contact_page_link
    has_about = p.has_about_page_link
    score = sum(1 for f in (has_privacy, has_terms, has_contact, has_about) if f) * 2.5
    if score >= 7.5:
        return Verdict("pass", 10.0, "info", 0.8,
                       {"privacy": has_privacy, "terms": has_terms, "contact": has_contact, "about": has_about})
    return Verdict("warn", max(4.0, score), "major", 0.8,
                   {"privacy": has_privacy, "terms": has_terms, "contact": has_contact, "about": has_about},
                   "Add visible About, Contact, Privacy Policy, and Terms or Refund pages.")


def check_author_credibility(p: ParsedHTML) -> Verdict:
    """ON-029 Author credibility analysis (heuristic)."""
    has_byline = bool(p.bylines)
    has_person_schema = any(
        (b.get("@type") == "Person" or (isinstance(b.get("@type"), list) and "Person" in b.get("@type", [])))
        for b in p.schema_blocks
    )
    has_author = any(
        isinstance(b.get("author"), (dict, list, str)) and b.get("author")
        for b in p.schema_blocks
    )
    score = sum(1 for f in (has_byline, has_person_schema, has_author) if f) * 3.5
    if score >= 7:
        return Verdict("pass", 10.0, "info", 0.8,
                       {"byline": has_byline, "person_schema": has_person_schema, "author_field": has_author})
    if p.word_count < 500:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "not a content page"})
    return Verdict("warn", 5.0, "major", 0.8,
                   {"byline": has_byline, "person_schema": has_person_schema, "author_field": has_author},
                   "Add a byline and Person schema with credentials for content pages.")


def check_eeat_overall(p: ParsedHTML) -> Verdict:
    """ON-026 E-E-A-T optimization analysis (heuristic rollup)."""
    ex = check_expertise_signals(p)
    tr = check_trust_signals(p)
    au = check_author_credibility(p)
    score = round((ex.score + tr.score + au.score) / 3.0, 1)
    status = status_from_score(score)
    sev = "major" if score < 6 else "minor"
    return Verdict(status, score, sev, 0.75,
                   {"expertise": ex.score, "trust": tr.score, "author": au.score})


def check_content_freshness(p: ParsedHTML) -> Verdict:
    """ON-032 Content freshness analysis."""
    dates = []
    for b in p.schema_blocks:
        for key in ("datePublished", "dateModified"):
            if key in b and b.get(key):
                dates.append(b.get(key))
    if dates:
        return Verdict("pass", 10.0, "info", 0.8, {"dates": dates[:2]})
    if p.word_count >= 500:
        return Verdict("warn", 6.0, "minor", 0.7, {"dates": []},
                       "Add datePublished and dateModified in Article schema to show freshness.")
    return Verdict("n_a", 0.0, "info", 0.7, {"dates": []})


def check_semantic_relevance(p: ParsedHTML) -> Verdict:
    """ON-033 Semantic relevance score (heuristic)."""
    primary = _primary_tokens(p)
    if not primary:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no primary tokens"})
    body_terms = set(_top_terms(p.body_text or "", n=12))
    overlap = len(primary & body_terms) / max(len(primary), 1)
    score = round(overlap * 10, 1)
    return Verdict(status_from_score(score), score, "minor" if score >= 6 else "major", 0.8,
                   {"overlap": round(overlap, 2), "primary": list(primary)[:3]})


def check_thin_content(p: ParsedHTML, *, threshold: int = 300) -> Verdict:
    """ON-023 Thin content detection (deterministic)."""
    if p.word_count < threshold:
        score = 0.0 if p.word_count < 100 else 4.0
        return Verdict(
            status="fail" if p.word_count < 100 else "warn",
            score=score,
            severity="critical" if p.word_count < 100 else "major",
            confidence=0.9,
            evidence={"word_count": p.word_count, "threshold": threshold},
            remediation=f"Only {p.word_count} words; deepen content past {threshold}+ to meet helpful-content baselines.",
        )
    return Verdict(
        "pass", 10.0, "info", 1.0, {"word_count": p.word_count, "threshold": threshold}
    )


def check_image_alt_text(p: ParsedHTML) -> Verdict:
    """ON-067 Image alt text optimization."""
    if not p.images:
        return Verdict("n_a", 0.0, "info", 1.0, {"images": 0})
    missing = [i.src for i in p.images if not i.alt]
    coverage = (len(p.images) - len(missing)) / len(p.images)
    score = round(coverage * 10, 1)
    if not missing:
        return Verdict("pass", 10.0, "info", 1.0, {"images": len(p.images), "missing_alt": 0})
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major" if coverage < 0.5 else "minor",
        confidence=1.0,
        evidence={"images": len(p.images), "missing_alt": len(missing), "examples": missing[:5]},
        remediation=f"{len(missing)} of {len(p.images)} images lack alt text.",
    )


def check_canonical_validation(p: ParsedHTML) -> Verdict:
    """ON-079 / TECH-019 Canonical tag validation."""
    if not p.canonical:
        return Verdict(
            "warn", 6.0, "major", 0.9,
            {"canonical": None},
            "Add a <link rel='canonical'> to declare the preferred URL.",
        )
    return Verdict(
        "pass", 10.0, "info", 1.0, {"canonical": p.canonical}
    )


def check_indexability(p: ParsedHTML) -> Verdict:
    """ON-080 Indexability analysis (on-page meta-robots view)."""
    if p.has_noindex:
        return Verdict(
            "fail", 0.0, "critical", 1.0,
            {"meta_robots": p.meta_robots, "noindex": True},
            "Page has meta noindex; remove unless intentional.",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"meta_robots": p.meta_robots or "(default)"})


def check_schema_validation(p: ParsedHTML) -> Verdict:
    """ON-073 / TECH-035 Schema markup validation."""
    if not p.schema_blocks:
        return Verdict(
            "warn", 5.0, "minor", 0.9,
            {"schema_blocks": 0},
            "No JSON-LD detected. Add Schema.org markup for the page type.",
        )
    results = validate_all(p.schema_blocks)
    errors_total = sum(len(r.errors) for r in results)
    if errors_total == 0:
        return Verdict(
            "pass", 10.0, "info", 1.0,
            {"blocks": len(results), "types": [r.type for r in results]},
        )
    score = max(1.0, 10.0 - errors_total * 2.0)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major" if errors_total >= 3 else "minor",
        confidence=1.0,
        evidence={
            "blocks": len(results),
            "errors_total": errors_total,
            "details": [{"type": r.type, "errors": r.errors} for r in results if r.errors],
        },
        remediation=f"{errors_total} schema validation error(s); fix per Schema.org spec.",
    )


def check_broken_internal_links(pages: list[CrawledPage]) -> Verdict:
    """ON-063 Broken internal links detection (site-wide)."""
    status_by_url = {p.url: p.http_status for p in pages}
    broken_targets: list[tuple[str, str, int]] = []
    for cp in pages:
        if not cp.parsed:
            continue
        for link in cp.parsed.links:
            if not link.is_internal:
                continue
            tgt_status = status_by_url.get(link.href)
            if tgt_status is not None and tgt_status >= 400:
                broken_targets.append((cp.url, link.href, tgt_status))
    if not broken_targets:
        return Verdict("pass", 10.0, "info", 1.0, {"broken_links": 0, "checked_pages": len(pages)})
    score = max(0.0, 10.0 - len(broken_targets))
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="critical",
        confidence=1.0,
        evidence={
            "broken_links": len(broken_targets),
            "examples": [
                {"from": s, "to": t, "status": st}
                for s, t, st in broken_targets[:10]
            ],
        },
        remediation=f"{len(broken_targets)} internal links point to non-2xx pages; fix or remove.",
    )


def check_orphan_pages(
    sitemap_urls: list[str], pages: list[CrawledPage]
) -> Verdict:
    """ON-061 Orphan page detection. A page is orphan if it appears in the
    sitemap but no other page links to it internally."""
    linked_to: set[str] = set()
    for cp in pages:
        if not cp.parsed:
            continue
        for link in cp.parsed.links:
            if link.is_internal:
                linked_to.add(link.href.rstrip("/"))
    orphans = [u for u in sitemap_urls if u.rstrip("/") not in linked_to]
    # Exclude homepage from orphan logic
    if pages:
        home = pages[0].url.rstrip("/")
        orphans = [o for o in orphans if o.rstrip("/") != home]
    if not orphans:
        return Verdict("pass", 10.0, "info", 1.0, {"orphans": 0})
    score = max(0.0, 10.0 - len(orphans) * 0.5)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="critical" if len(orphans) >= 5 else "major",
        confidence=0.85,
        evidence={"orphan_count": len(orphans), "examples": orphans[:10]},
        remediation=f"{len(orphans)} pages have no internal links; add contextual links from related pages.",
    )


def check_https(cp: CrawledPage) -> Verdict:
    """ON-099 / TECH-055 HTTPS validation."""
    if cp.final_url.startswith("https://"):
        return Verdict("pass", 10.0, "info", 1.0, {"scheme": "https"})
    return Verdict(
        "fail", 0.0, "critical", 1.0,
        {"scheme": "http", "url": cp.final_url},
        "Serve all pages over HTTPS; redirect HTTP to HTTPS site-wide.",
    )


def check_viewport(p: ParsedHTML) -> Verdict:
    """TECH-066 Viewport configuration analysis."""
    if not p.viewport:
        return Verdict(
            "fail", 0.0, "major", 1.0, {"viewport": None},
            "Add <meta name='viewport' content='width=device-width, initial-scale=1'>.",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"viewport": p.viewport})


def check_hreflang(p: ParsedHTML) -> Verdict:
    """TECH-061 Hreflang validation (light)."""
    if not p.hreflang:
        return Verdict("n_a", 0.0, "info", 1.0, {"hreflang_count": 0})
    # Simple sanity: codes look like lang or lang-region.
    bad = [
        e.lang
        for e in p.hreflang
        if not re.fullmatch(r"[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?|x-default", e.lang)
    ]
    if bad:
        return Verdict(
            "fail", 4.0, "major", 1.0,
            {"invalid_codes": bad[:10], "total": len(p.hreflang)},
            f"Hreflang codes invalid: {bad[:5]}. Use BCP-47 (e.g., en-US, fr, x-default).",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"hreflang_count": len(p.hreflang)})


def check_keyword_cannibalization(pages: list[ParsedHTML]) -> Verdict:
    """ON-013 Keyword cannibalization detection.

    Heuristic: two pages with effectively identical title (post-normalize) target
    the same SERP and risk cannibalization."""
    by_norm: defaultdict[str, list[str]] = defaultdict(list)
    for p in pages:
        if not p.title:
            continue
        norm = re.sub(r"\s+", " ", p.title.lower().strip())
        by_norm[norm].append(p.url)
    cannibals = {t: urls for t, urls in by_norm.items() if len(urls) > 1}
    if not cannibals:
        return Verdict("pass", 10.0, "info", 1.0, {"clashes": 0})
    score = max(0.0, 10.0 - len(cannibals) * 2.0)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="critical" if len(cannibals) >= 3 else "major",
        confidence=0.7,
        evidence={
            "clashes": len(cannibals),
            "examples": [{"title": t, "urls": urls} for t, urls in list(cannibals.items())[:5]],
        },
        remediation=(
            f"{len(cannibals)} title clashes detected; differentiate intent or consolidate pages."
        ),
    )


def check_meta_description_uniqueness(pages: list[ParsedHTML]) -> dict[str, Verdict]:
    """ON-040 Meta description uniqueness (site-wide)."""
    descs = [(p.url, (p.meta_description or "").strip()) for p in pages if p.meta_description]
    if not descs:
        return {}
    seen: dict[str, list[str]] = {}
    for url, d in descs:
        seen.setdefault(d, []).append(url)
    dupes = {d: urls for d, urls in seen.items() if len(urls) > 1}
    out: dict[str, Verdict] = {}
    for url, d in descs:
        dup_count = len(seen.get(d, []))
        if dup_count > 1:
            out[url] = Verdict(
                "fail", 4.0, "major", 1.0,
                {"duplicate_count": dup_count},
                "Meta description is duplicated across pages. Make each unique to the page intent.",
            )
        else:
            out[url] = Verdict("pass", 10.0, "info", 1.0, {"duplicate_count": 1})
    return out


def check_link_equity_distribution(pages: list[CrawledPage]) -> Verdict:
    """ON-062 Link equity distribution analysis (site-wide)."""
    if not pages:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no pages"})
    inbound: defaultdict[str, int] = defaultdict(int)
    for cp in pages:
        if not cp.parsed:
            continue
        for link in cp.parsed.links:
            if link.is_internal:
                inbound[link.href] += 1
    if not inbound:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no internal links"})
    counts = list(inbound.values())
    avg = mean(counts) if counts else 0.0
    if avg == 0:
        return Verdict("n_a", 0.0, "info", 1.0, {"reason": "no inbound counts"})
    spread = max(counts) / avg if avg else 0.0
    if spread <= 3.0:
        return Verdict("pass", 10.0, "info", 0.85, {"avg_inbound": round(avg, 2), "max_over_avg": round(spread, 2)})
    return Verdict("warn", 6.0, "minor", 0.8, {"avg_inbound": round(avg, 2), "max_over_avg": round(spread, 2)},
                   "Redistribute internal links so key pages receive more consistent link equity.")


def iter_per_page_checks(p: ParsedHTML) -> Iterable[tuple[str, str, Verdict]]:
    """Yield (check_id, owner_agent, verdict) for the per-page analyzer set.

    Used by the orchestrator to flatten findings into rows."""
    yield ("ON-034", "A3", check_title_tag(p))
    yield ("ON-035", "A3", check_title_ctr(p))
    yield ("ON-037", "A3", check_title_keyword_placement(p))
    yield ("ON-038", "A3", check_meta_description(p))
    yield ("ON-039", "A3", check_meta_ctr(p))
    yield ("ON-041", "A3", check_h1_optimization(p))
    yield ("ON-042", "A3", check_multiple_h1(p))
    yield ("ON-043", "A3", check_heading_hierarchy(p))
    yield ("ON-044", "A3", check_heading_semantics(p))
    yield ("ON-045", "A3", check_heading_questions(p))
    yield ("ON-046", "A5", check_featured_snippet(p))
    yield ("ON-047", "A5", check_passage_ranking(p))
    yield ("ON-048", "A5", check_ai_overview(p))
    yield ("ON-049", "A5", check_direct_answer(p))
    yield ("ON-050", "A3", check_faq_optimization(p))
    yield ("ON-051", "A1", check_readability(p))
    yield ("ON-053", "A1", check_paragraph_length(p))
    yield ("ON-054", "A1", check_sentence_complexity(p))
    yield ("ON-055", "A1", check_scannability(p))
    yield ("ON-056", "A1", check_intro_optimization(p))
    yield ("ON-058", "A4", check_anchor_text_optimization(p))
    yield ("ON-065", "A4", check_external_link_quality(p))
    yield ("ON-066", "A4", check_outbound_authority(p))
    yield ("ON-069", "A3", check_image_filename(p))
    yield ("ON-071", "A3", check_webp_usage(p))
    yield ("ON-072", "A3", check_lazy_loading(p))
    yield ("ON-073", "B4", check_schema_validation(p))
    yield ("ON-074", "B4", check_faq_schema(p))
    yield ("ON-075", "B4", check_article_schema(p))
    yield ("ON-076", "B4", check_service_schema(p))
    yield ("ON-077", "B4", check_breadcrumb_schema(p))
    yield ("ON-078", "B4", check_rich_result_eligibility(p))
    yield ("ON-022", "A1", check_content_depth(p))
    yield ("ON-006", "A2", check_primary_keyword_optimization(p))
    yield ("ON-007", "A2", check_secondary_keywords(p))
    yield ("ON-011", "A2", check_keyword_stuffing(p))
    yield ("ON-014", "A2", check_related_entities(p))
    yield ("ON-026", "A1", check_eeat_overall(p))
    yield ("ON-027", "A1", check_expertise_signals(p))
    yield ("ON-028", "A1", check_trust_signals(p))
    yield ("ON-029", "A1", check_author_credibility(p))
    yield ("ON-032", "A1", check_content_freshness(p))
    yield ("ON-033", "A2", check_semantic_relevance(p))
    yield ("ON-023", "A1", check_thin_content(p))
    yield ("ON-067", "A3", check_image_alt_text(p))
    yield ("ON-079", "B1", check_canonical_validation(p))
    yield ("ON-080", "B1", check_indexability(p))
    yield ("TECH-066", "B2", check_viewport(p))
    yield ("TECH-061", "B5", check_hreflang(p))
